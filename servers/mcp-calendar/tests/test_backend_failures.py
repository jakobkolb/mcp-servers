"""A failing backend must not hide the others; a rate-limited one must be left alone for a while."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from caldav.lib.error import RateLimitError
from mcp_calendar import tools
from mcp_calendar.backends import (
    DEFAULT_RATE_LIMIT_COOLDOWN,
    MAX_RATE_LIMIT_COOLDOWN,
    BackendUnavailableError,
    CaldavBackend,
)
from mcp_calendar.calendar import CalendarEvent, CalendarTask
from mcp_calendar.tools import (
    GetFreeBusyToolHandler,
    ListCalendarsToolHandler,
    ListEventsToolHandler,
    ListTasksToolHandler,
)

START = datetime(2024, 6, 5, 9, 0, tzinfo=UTC)
END = datetime(2024, 6, 5, 18, 0, tzinfo=UTC)
RANGE = {"start": START.isoformat(), "end": END.isoformat()}


def _limited(seconds: float | None = 60.0) -> RateLimitError:
    return RateLimitError(
        url="https://caldav.icloud.com/",
        reason="Rate limited or service unavailable",
        retry_after=None if seconds is None else str(int(seconds)),
        retry_after_seconds=seconds,
    )


def _backend(name: str, **methods: object) -> MagicMock:
    backend = MagicMock()
    backend.name = name
    for method, outcome in methods.items():
        if isinstance(outcome, Exception):
            getattr(backend, method).side_effect = outcome
        else:
            getattr(backend, method).return_value = outcome
    return backend


def _event(backend: str) -> CalendarEvent:
    return CalendarEvent(
        uid="u1",
        summary="Meeting",
        start=START,
        end=END,
        calendar_name="Work",
        backend_name=backend,
    )


def _task(backend: str) -> CalendarTask:
    return CalendarTask(
        uid="t1",
        summary="Buy milk",
        due=date(2024, 7, 1),
        priority=0,
        status="NEEDS-ACTION",
        calendar_name="Tasks",
        backend_name=backend,
    )


@pytest.fixture
def use_backends(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def install(*backends: MagicMock) -> None:
        monkeypatch.setattr(tools, "_backends", list(backends))

    return install


# --- the tools: partial results instead of one failure for all ---------------------------


def test_nothing_changes_when_every_backend_answers(use_backends) -> None:  # type: ignore[no-untyped-def]
    use_backends(
        _backend("icloud", list_calendars=["Home"]), _backend("work", list_calendars=["Office"])
    )

    result = ListCalendarsToolHandler().run_tool({})

    assert len(result) == 1
    assert json.loads(result[0].text) == {"icloud": ["Home"], "work": ["Office"]}  # type: ignore[union-attr]


def test_a_rate_limited_backend_does_not_hide_the_others(use_backends) -> None:  # type: ignore[no-untyped-def]
    use_backends(
        _backend("icloud", list_calendars=_limited(60)), _backend("work", list_calendars=["Office"])
    )

    result = ListCalendarsToolHandler().run_tool({})

    assert json.loads(result[0].text) == {"work": ["Office"]}  # type: ignore[union-attr]
    warning = result[1].text  # type: ignore[union-attr]
    assert "WARNING: incomplete result" in warning
    assert "icloud: rate limited by the server, retry after 60 s" in warning
    assert "work:" not in warning


def test_other_errors_are_reported_per_backend_too(use_backends) -> None:  # type: ignore[no-untyped-def]
    use_backends(
        _backend("icloud", list_calendars=RuntimeError("boom")),
        _backend("work", list_calendars=["Office"]),
    )

    result = ListCalendarsToolHandler().run_tool({})

    assert "icloud: RuntimeError: boom" in result[1].text  # type: ignore[union-attr]


def test_a_backend_in_its_cooldown_is_described_as_such(use_backends) -> None:  # type: ignore[no-untyped-def]
    use_backends(
        _backend("icloud", list_calendars=BackendUnavailableError("icloud", 42.0)),
        _backend("work", list_calendars=["Office"]),
    )

    result = ListCalendarsToolHandler().run_tool({})

    assert "not contacted for another 42 s" in result[1].text  # type: ignore[union-attr]


def test_it_raises_only_when_every_backend_failed(use_backends) -> None:  # type: ignore[no-untyped-def]
    use_backends(
        _backend("icloud", list_calendars=_limited(60)),
        _backend("work", list_calendars=RuntimeError("down")),
    )

    with pytest.raises(RuntimeError, match=r"icloud: rate limited.*work: RuntimeError: down"):
        ListCalendarsToolHandler().run_tool({})


def test_asking_for_one_backend_that_fails_raises(use_backends) -> None:  # type: ignore[no-untyped-def]
    use_backends(
        _backend("icloud", list_events=_limited(60)), _backend("work", list_events=[_event("work")])
    )

    with pytest.raises(RuntimeError, match="icloud"):
        ListEventsToolHandler().run_tool({**RANGE, "backend": "icloud"})


def test_no_backends_still_gives_an_empty_answer(use_backends) -> None:  # type: ignore[no-untyped-def]
    use_backends()

    result = ListCalendarsToolHandler().run_tool({})

    assert json.loads(result[0].text) == {}  # type: ignore[union-attr]
    assert len(result) == 1


def test_list_events_returns_the_healthy_backends_events(use_backends) -> None:  # type: ignore[no-untyped-def]
    use_backends(
        _backend("icloud", list_events=_limited(60)), _backend("work", list_events=[_event("work")])
    )

    result = ListEventsToolHandler().run_tool(RANGE)

    events = json.loads(result[0].text)  # type: ignore[union-attr]
    assert [e["backend_name"] for e in events] == ["work"]
    assert "icloud: rate limited" in result[1].text  # type: ignore[union-attr]


def test_free_busy_returns_the_healthy_backends_slots(use_backends) -> None:  # type: ignore[no-untyped-def]
    use_backends(
        _backend("icloud", get_freebusy=_limited(60)),
        _backend("work", get_freebusy=[(START, END)]),
    )

    result = GetFreeBusyToolHandler().run_tool(RANGE)

    assert json.loads(result[0].text) == {"work": [[START.isoformat(), END.isoformat()]]}  # type: ignore[union-attr]
    assert "icloud: rate limited" in result[1].text  # type: ignore[union-attr]


def test_list_tasks_returns_the_healthy_backends_tasks(use_backends) -> None:  # type: ignore[no-untyped-def]
    use_backends(
        _backend("icloud", list_tasks=_limited(60)), _backend("work", list_tasks=[_task("work")])
    )

    result = ListTasksToolHandler().run_tool({})

    assert [t["uid"] for t in json.loads(result[0].text)] == ["t1"]  # type: ignore[union-attr]
    assert "icloud: rate limited" in result[1].text  # type: ignore[union-attr]


# --- the backend: honour Retry-After ----------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():  # type: ignore[no-untyped-def]
    c = Clock()
    with patch("mcp_calendar.backends.monotonic", c):
        yield c


def _caldav_backend(name: str = "icloud") -> tuple[CaldavBackend, MagicMock]:
    backend = CaldavBackend(
        name=name, url="https://caldav.example.com/", username="user", password="pass"
    )
    client = MagicMock()
    cal = MagicMock()
    cal.name = "Home"
    client.principal.return_value.calendars.return_value = [cal]
    return backend, client


def _discoveries(client: MagicMock) -> int:
    return client.principal.call_count  # type: ignore[no-any-return]


def test_a_rate_limited_backend_is_left_alone_until_retry_after(clock: Clock) -> None:
    backend, client = _caldav_backend()
    client.principal.return_value.calendars.side_effect = _limited(60)

    with patch("mcp_calendar.backends.caldav.DAVClient", return_value=client):
        with pytest.raises(RateLimitError):
            backend.list_calendars()
        assert _discoveries(client) == 1

        clock.now += 30
        with pytest.raises(BackendUnavailableError) as blocked:
            backend.list_calendars()
        assert blocked.value.retry_in == pytest.approx(30)
        assert _discoveries(client) == 1  # not contacted again

        clock.now += 31  # 61 s after the error
        client.principal.return_value.calendars.side_effect = None
        assert backend.list_calendars() == ["Home"]
        assert _discoveries(client) == 2


def test_without_a_retry_after_value_it_waits_the_default(clock: Clock) -> None:
    backend, client = _caldav_backend()
    client.principal.return_value.calendars.side_effect = _limited(None)

    with patch("mcp_calendar.backends.caldav.DAVClient", return_value=client):
        with pytest.raises(RateLimitError):
            backend.list_calendars()
        clock.now += DEFAULT_RATE_LIMIT_COOLDOWN - 1
        with pytest.raises(BackendUnavailableError):
            backend.list_calendars()
        clock.now += 2
        with pytest.raises(RateLimitError):  # contacted again, and limited again
            backend.list_calendars()
        assert _discoveries(client) == 2


def test_a_huge_retry_after_is_capped(clock: Clock) -> None:
    backend, client = _caldav_backend()
    client.principal.return_value.calendars.side_effect = _limited(10**9)

    with patch("mcp_calendar.backends.caldav.DAVClient", return_value=client):
        with pytest.raises(RateLimitError):
            backend.list_calendars()
        clock.now += MAX_RATE_LIMIT_COOLDOWN + 1
        with pytest.raises(RateLimitError):
            backend.list_calendars()
        assert _discoveries(client) == 2


def test_other_errors_do_not_start_a_cooldown(clock: Clock) -> None:
    backend, client = _caldav_backend()
    client.principal.return_value.calendars.side_effect = RuntimeError("boom")

    with patch("mcp_calendar.backends.caldav.DAVClient", return_value=client):
        for _ in range(2):
            with pytest.raises(RuntimeError):
                backend.list_calendars()
        assert _discoveries(client) == 2


def test_every_server_facing_method_respects_the_cooldown(clock: Clock) -> None:
    backend, client = _caldav_backend()
    client.principal.return_value.calendars.side_effect = _limited(60)

    with patch("mcp_calendar.backends.caldav.DAVClient", return_value=client):
        with pytest.raises(RateLimitError):
            backend.list_calendars()
        attempts = [
            lambda: backend.list_events(START, END),
            lambda: backend.get_freebusy(START, END),
            lambda: backend.list_tasks(),
            lambda: backend.create_event("x", START, END),
            lambda: backend.delete_event("uid"),
            lambda: backend.delete_task("uid"),
        ]
        for attempt in attempts:
            with pytest.raises(BackendUnavailableError):
                attempt()
        assert _discoveries(client) == 1


def test_the_cooldown_is_per_backend(clock: Clock) -> None:
    limited, limited_client = _caldav_backend("icloud")
    healthy, healthy_client = _caldav_backend("work")
    limited_client.principal.return_value.calendars.side_effect = _limited(60)

    with patch("mcp_calendar.backends.caldav.DAVClient", return_value=limited_client):
        with pytest.raises(RateLimitError):
            limited.list_calendars()
    with patch("mcp_calendar.backends.caldav.DAVClient", return_value=healthy_client):
        assert healthy.list_calendars() == ["Home"]
