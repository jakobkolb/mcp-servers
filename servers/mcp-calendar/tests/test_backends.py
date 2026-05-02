"""Tests for CalDAV backend implementations."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

from mcp_calendar.backends import CaldavBackend, GoogleBackend, ICloudBackend, NextcloudBackend
from mcp_calendar.calendar import CalendarEvent
from mcp_calendar.config import GoogleConfig, ICloudConfig, NextcloudConfig


def _make_backend(name: str = "test") -> CaldavBackend:
    return CaldavBackend(
        name=name,
        url="https://caldav.example.com/",
        username="user",
        password="pass",
    )


def _mock_cal(name: str = "Work") -> MagicMock:
    cal = MagicMock()
    cal.name = name
    return cal


def _mock_ical_event(
    uid: str = "uid-1",
    summary: str = "Meeting",
    start: datetime | date = datetime(2024, 6, 1, 10, 0, tzinfo=UTC),
    end: datetime | date = datetime(2024, 6, 1, 11, 0, tzinfo=UTC),
) -> MagicMock:
    comp = MagicMock()
    comp.get = lambda key, default=None: {  # type: ignore[misc]
        "uid": uid,
        "summary": summary,
        "dtstart": MagicMock(dt=start),
        "dtend": MagicMock(dt=end),
        "description": None,
        "location": None,
    }.get(key, default)
    event = MagicMock()
    event.icalendar_component = comp
    return event


# ---------------------------------------------------------------------------
# list_calendars
# ---------------------------------------------------------------------------


def test_list_calendars() -> None:
    backend = _make_backend()
    cal1 = _mock_cal("Personal")
    cal2 = _mock_cal("Work")

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal1, cal2]
        result = backend.list_calendars()

    assert result == ["Personal", "Work"]


# ---------------------------------------------------------------------------
# list_events
# ---------------------------------------------------------------------------


def test_list_events() -> None:
    backend = _make_backend()
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = datetime(2024, 6, 30, tzinfo=UTC)
    cal = _mock_cal("Work")
    raw_event = _mock_ical_event()
    cal.date_search.return_value = [raw_event]

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        events = backend.list_events(start, end)

    assert len(events) == 1
    assert isinstance(events[0], CalendarEvent)
    assert events[0].summary == "Meeting"
    assert events[0].uid == "uid-1"
    assert events[0].calendar_name == "Work"
    assert events[0].backend_name == "test"


def test_list_events_handles_error() -> None:
    """Calendar that raises should not prevent results from other calendars."""
    backend = _make_backend()
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = datetime(2024, 6, 30, tzinfo=UTC)

    bad_cal = _mock_cal("Bad")
    bad_cal.date_search.side_effect = RuntimeError("connection failed")

    good_cal = _mock_cal("Good")
    good_event = _mock_ical_event(uid="uid-ok", summary="OK")
    good_cal.date_search.return_value = [good_event]

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [bad_cal, good_cal]
        events = backend.list_events(start, end)

    assert len(events) == 1
    assert events[0].summary == "OK"


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------


def test_create_event() -> None:
    backend = _make_backend()
    cal = _mock_cal("Personal")
    start = datetime(2024, 7, 1, 9, 0, tzinfo=UTC)
    end = datetime(2024, 7, 1, 10, 0, tzinfo=UTC)

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        event = backend.create_event(
            summary="Team sync",
            start=start,
            end=end,
            description="Weekly standup",
        )

    cal.save_event.assert_called_once()
    call_arg = cal.save_event.call_args[0][0]
    assert isinstance(call_arg, bytes)
    assert b"Team sync" in call_arg

    assert isinstance(event, CalendarEvent)
    assert event.summary == "Team sync"
    assert event.start == start
    assert event.end == end
    assert event.description == "Weekly standup"
    assert event.backend_name == "test"


# ---------------------------------------------------------------------------
# update_event
# ---------------------------------------------------------------------------


def test_update_event() -> None:
    backend = _make_backend()
    cal = _mock_cal("Work")
    uid = "uid-to-update"
    original_start = datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
    original_end = datetime(2024, 6, 1, 11, 0, tzinfo=UTC)
    raw = _mock_ical_event(uid=uid, summary="Old title", start=original_start, end=original_end)
    cal.event_by_uid.return_value = raw

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        updated = backend.update_event(uid=uid, summary="New title")

    assert raw.save.called
    assert isinstance(raw.data, str)
    assert updated.summary == "New title"
    assert updated.uid == uid


# ---------------------------------------------------------------------------
# delete_event
# ---------------------------------------------------------------------------


def test_delete_event() -> None:
    backend = _make_backend()
    cal = _mock_cal("Work")
    uid = "uid-to-delete"
    raw = _mock_ical_event(uid=uid)
    cal.event_by_uid.return_value = raw

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        backend.delete_event(uid)

    raw.delete.assert_called_once()


# ---------------------------------------------------------------------------
# get_freebusy
# ---------------------------------------------------------------------------


def test_get_freebusy() -> None:
    backend = _make_backend()
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = datetime(2024, 6, 30, tzinfo=UTC)
    ev1_start = datetime(2024, 6, 5, 9, 0, tzinfo=UTC)
    ev1_end = datetime(2024, 6, 5, 10, 0, tzinfo=UTC)
    ev2_start = datetime(2024, 6, 10, 14, 0, tzinfo=UTC)
    ev2_end = datetime(2024, 6, 10, 15, 0, tzinfo=UTC)

    event1 = CalendarEvent(uid="1", summary="A", start=ev1_start, end=ev1_end)
    event2 = CalendarEvent(uid="2", summary="B", start=ev2_start, end=ev2_end)

    with patch.object(backend, "list_events", return_value=[event1, event2]):
        slots = backend.get_freebusy(start, end)

    assert len(slots) == 2
    assert slots[0] == (ev1_start, ev1_end)
    assert slots[1] == (ev2_start, ev2_end)


def test_get_freebusy_all_day_event() -> None:
    """All-day events (bare date) must be converted to datetime."""
    backend = _make_backend()
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = datetime(2024, 6, 30, tzinfo=UTC)

    ev = CalendarEvent(
        uid="allday",
        summary="Holiday",
        start=date(2024, 6, 10),
        end=date(2024, 6, 11),
    )

    with patch.object(backend, "list_events", return_value=[ev]):
        slots = backend.get_freebusy(start, end)

    assert len(slots) == 1
    slot_start, slot_end = slots[0]
    assert isinstance(slot_start, datetime)
    assert isinstance(slot_end, datetime)
    assert slot_start.date() == date(2024, 6, 10)


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


def test_icloud_url() -> None:
    cfg = ICloudConfig(name="ic", username="u@icloud.com", password="p")
    backend = ICloudBackend(cfg)
    assert backend._url == "https://caldav.icloud.com/"


def test_google_url() -> None:
    cfg = GoogleConfig(name="goog", username="user@gmail.com", password="p")
    backend = GoogleBackend(cfg)
    assert "user@gmail.com" in backend._url
    assert "apidata.googleusercontent.com" in backend._url


def test_nextcloud_url() -> None:
    cfg = NextcloudConfig(name="nc", url="https://cloud.example.com", username="u", password="p")
    backend = NextcloudBackend(cfg)
    assert backend._url.endswith("/remote.php/dav/")
