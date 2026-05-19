"""Tests for CalDAV backend implementations."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock, patch

import icalendar
import pytest
from mcp_calendar.backends import CaldavBackend, GoogleBackend, ICloudBackend, NextcloudBackend
from mcp_calendar.calendar import CalendarEvent, CalendarTask, UnsupportedOperationError
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
    alarm_offsets_minutes: list[int] | None = None,
) -> MagicMock:
    # Build a real iCal string so update_event's in-place patching can parse event.data
    cal_obj = icalendar.Calendar()
    cal_obj.add("prodid", "-//mcp-calendar//EN")
    cal_obj.add("version", "2.0")
    event_comp_real = icalendar.Event()
    event_comp_real.add("uid", uid)
    event_comp_real.add("summary", summary)
    event_comp_real.add("dtstart", start)
    event_comp_real.add("dtend", end)
    for minutes in alarm_offsets_minutes or []:
        alarm = icalendar.Alarm()
        alarm.add("ACTION", "DISPLAY")
        alarm.add("DESCRIPTION", "Reminder")
        alarm.add("TRIGGER", timedelta(minutes=-minutes))
        event_comp_real.add_component(alarm)
    cal_obj.add_component(event_comp_real)
    ical_str = cal_obj.to_ical().decode("utf-8")

    # Keep the mock component for _parse_event (reads via icalendar_component)
    comp = MagicMock()
    comp.get = lambda key, default=None: {  # type: ignore[misc]
        "uid": uid,
        "summary": summary,
        "dtstart": MagicMock(dt=start),
        "dtend": MagicMock(dt=end),
        "description": None,
        "location": None,
    }.get(key, default)

    alarm_mocks: list[MagicMock] = []
    for minutes in alarm_offsets_minutes or []:
        alarm_comp = MagicMock()
        alarm_comp.name = "VALARM"
        trigger_mock = MagicMock()
        trigger_mock.dt = timedelta(minutes=-minutes)
        alarm_comp.get = lambda key, default=None, _t=trigger_mock: {  # type: ignore[misc]
            "TRIGGER": _t,
        }.get(key, default)
        alarm_mocks.append(alarm_comp)

    comp.walk.return_value = [comp] + alarm_mocks

    event = MagicMock()
    event.icalendar_component = comp
    event.data = ical_str
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


# ---------------------------------------------------------------------------
# Helpers for VTODO tests
# ---------------------------------------------------------------------------

_VTODO_TEMPLATE = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//mcp-calendar//EN\r\n"
    "BEGIN:VTODO\r\n"
    "UID:{uid}\r\n"
    "SUMMARY:{summary}\r\n"
    "STATUS:NEEDS-ACTION\r\n"
    "PRIORITY:0\r\n"
    "END:VTODO\r\n"
    "END:VCALENDAR\r\n"
)


def _mock_ical_task(
    uid: str = "task-1",
    summary: str = "Buy milk",
    due: date | None = None,
    priority: int = 0,
    status: str = "NEEDS-ACTION",
    description: str | None = None,
) -> MagicMock:
    comp = MagicMock()
    comp.get = lambda key, default=None: {  # type: ignore[misc]
        "uid": uid,
        "summary": summary,
        "due": MagicMock(dt=due) if due else None,
        "priority": priority,
        "status": status,
        "description": description,
    }.get(key, default)
    task = MagicMock()
    task.icalendar_component = comp
    task.data = _VTODO_TEMPLATE.format(uid=uid, summary=summary)
    return task


# ---------------------------------------------------------------------------
# CalendarTask dataclass
# ---------------------------------------------------------------------------


def test_calendar_task_to_dict() -> None:
    task = CalendarTask(
        uid="t-1",
        summary="Buy milk",
        description="Whole milk",
        due=date(2024, 7, 1),
        priority=5,
        status="NEEDS-ACTION",
        calendar_name="Tasks",
        backend_name="icloud",
    )
    d = task.to_dict()
    assert d["uid"] == "t-1"
    assert d["summary"] == "Buy milk"
    assert d["description"] == "Whole milk"
    assert d["due"] == "2024-07-01"
    assert d["priority"] == 5
    assert d["status"] == "NEEDS-ACTION"
    assert d["calendar_name"] == "Tasks"
    assert d["backend_name"] == "icloud"


def test_calendar_task_to_dict_no_due() -> None:
    task = CalendarTask(uid="t-2", summary="Reminder")
    assert task.to_dict()["due"] is None


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------


def test_create_task() -> None:
    backend = _make_backend()
    cal = _mock_cal("Tasks")

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        task = backend.create_task(summary="Write tests")

    cal.save_event.assert_called_once()
    raw: bytes = cal.save_event.call_args[0][0]
    assert b"VTODO" in raw
    assert b"Write tests" in raw

    assert isinstance(task, CalendarTask)
    assert task.summary == "Write tests"
    assert task.backend_name == "test"
    assert task.calendar_name == "Tasks"


def test_create_task_with_optional_fields() -> None:
    backend = _make_backend()
    cal = _mock_cal("Tasks")
    due = date(2024, 8, 1)

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        task = backend.create_task(
            summary="Important task",
            description="Must not forget",
            due=due,
            priority=1,
        )

    raw: bytes = cal.save_event.call_args[0][0]
    assert b"Important task" in raw
    assert b"Must not forget" in raw
    assert b"20240801" in raw
    assert b"PRIORITY:1" in raw

    assert task.description == "Must not forget"
    assert task.due == due
    assert task.priority == 1


def test_create_task_target_calendar() -> None:
    backend = _make_backend()
    cal1 = _mock_cal("Personal")
    cal2 = _mock_cal("Work Tasks")

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal1, cal2]
        backend.create_task(summary="Work item", calendar_name="Work Tasks")

    cal1.save_event.assert_not_called()
    cal2.save_event.assert_called_once()


def test_create_task_calendar_not_found() -> None:
    backend = _make_backend()
    cal = _mock_cal("Tasks")

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        with pytest.raises(ValueError, match="not found"):
            backend.create_task(summary="X", calendar_name="Nonexistent")


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------


def test_update_task_summary() -> None:
    backend = _make_backend()
    cal = _mock_cal("Tasks")
    uid = "task-to-update"
    raw_task = _mock_ical_task(uid=uid, summary="Old summary")
    cal.event_by_uid.return_value = raw_task

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        updated = backend.update_task(uid=uid, summary="New summary")

    assert raw_task.save.called
    assert updated.summary == "New summary"
    assert updated.uid == uid


def test_update_task_status() -> None:
    backend = _make_backend()
    cal = _mock_cal("Tasks")
    uid = "task-status"
    raw_task = _mock_ical_task(uid=uid, summary="Do something")
    cal.event_by_uid.return_value = raw_task

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        updated = backend.update_task(uid=uid, status="COMPLETED")

    assert raw_task.save.called
    assert updated.status == "COMPLETED"


def test_update_task_not_found() -> None:
    backend = _make_backend()
    cal = _mock_cal("Tasks")
    cal.event_by_uid.side_effect = Exception("not found")

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        with pytest.raises(ValueError, match="not found"):
            backend.update_task(uid="ghost-uid", summary="X")


def test_update_task_patches_in_place() -> None:
    """update_task must modify the existing iCal data, not rebuild from scratch."""
    backend = _make_backend()
    cal = _mock_cal("Tasks")
    uid = "task-inplace"
    # Include a custom property that would be lost if rebuilt from scratch
    custom_vtodo = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VTODO\r\n"
        f"UID:{uid}\r\n"
        "SUMMARY:Original\r\n"
        "STATUS:NEEDS-ACTION\r\n"
        "PRIORITY:0\r\n"
        "X-CUSTOM-PROP:keep-me\r\n"
        "END:VTODO\r\n"
        "END:VCALENDAR\r\n"
    )
    raw_task = MagicMock()
    raw_task.data = custom_vtodo
    raw_task.icalendar_component = _mock_ical_task(uid=uid, summary="Original").icalendar_component
    cal.event_by_uid.return_value = raw_task

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        backend.update_task(uid=uid, summary="Updated")

    # The saved data should still contain the custom property
    assert raw_task.save.called
    saved_data: str = raw_task.data
    assert "X-CUSTOM-PROP" in saved_data
    assert "Updated" in saved_data


# ---------------------------------------------------------------------------
# delete_task
# ---------------------------------------------------------------------------


def test_delete_task() -> None:
    backend = _make_backend()
    cal = _mock_cal("Tasks")
    uid = "task-to-delete"
    raw_task = _mock_ical_task(uid=uid)
    cal.event_by_uid.return_value = raw_task

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        backend.delete_task(uid)

    raw_task.delete.assert_called_once()


def test_delete_task_not_found() -> None:
    backend = _make_backend()
    cal = _mock_cal("Tasks")
    cal.event_by_uid.side_effect = Exception("not found")

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        with pytest.raises(ValueError, match="not found"):
            backend.delete_task("ghost-uid")


# ---------------------------------------------------------------------------
# GoogleBackend raises UnsupportedOperationError for task writes
# ---------------------------------------------------------------------------


def test_google_create_task_raises_unsupported() -> None:
    cfg = GoogleConfig(name="goog", username="user@gmail.com", password="p")
    backend = GoogleBackend(cfg)

    with patch("mcp_calendar.backends.caldav.DAVClient"):
        with pytest.raises(UnsupportedOperationError):
            backend.create_task(summary="Nope")


def test_google_update_task_raises_unsupported() -> None:
    cfg = GoogleConfig(name="goog", username="user@gmail.com", password="p")
    backend = GoogleBackend(cfg)

    with patch("mcp_calendar.backends.caldav.DAVClient"):
        with pytest.raises(UnsupportedOperationError):
            backend.update_task(uid="some-uid", summary="Nope")


def test_google_delete_task_raises_unsupported() -> None:
    cfg = GoogleConfig(name="goog", username="user@gmail.com", password="p")
    backend = GoogleBackend(cfg)

    with patch("mcp_calendar.backends.caldav.DAVClient"):
        with pytest.raises(UnsupportedOperationError):
            backend.delete_task("some-uid")


# ---------------------------------------------------------------------------
# NextcloudConfig task_list_filter
# ---------------------------------------------------------------------------


def test_nextcloud_task_list_filter_config() -> None:
    cfg = NextcloudConfig(
        name="nc",
        url="https://cloud.example.com",
        username="u",
        password="p",
        task_list_filter="My Tasks",
    )
    backend = NextcloudBackend(cfg)
    assert backend._task_filter == "My Tasks"


# ---------------------------------------------------------------------------
# Connection / calendar-list caching
# ---------------------------------------------------------------------------


def test_client_is_cached_across_calls() -> None:
    """DAVClient must be instantiated only once even when two methods are called."""
    backend = _make_backend()
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = datetime(2024, 6, 30, tzinfo=UTC)

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = []
        backend.list_calendars()
        backend.list_events(start, end)

    MockClient.assert_called_once()


def test_calendars_are_cached_across_calls() -> None:
    """principal().calendars() must be called only once across multiple methods."""
    backend = _make_backend()
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = datetime(2024, 6, 30, tzinfo=UTC)

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = []
        backend.list_calendars()
        backend.list_events(start, end)

    MockClient.return_value.principal.return_value.calendars.assert_called_once()


def test_cache_invalidated_on_connection_error() -> None:
    """On a connection failure the cache is cleared so the next call reconnects."""
    backend = _make_backend()
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = datetime(2024, 6, 30, tzinfo=UTC)

    good_cal = _mock_cal("Work")
    good_cal.date_search.return_value = [_mock_ical_event()]

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        # First call: principal().calendars() raises a connection error
        MockClient.return_value.principal.return_value.calendars.side_effect = Exception(
            "connection refused"
        )
        with pytest.raises(Exception, match="connection refused"):
            backend.list_events(start, end)

        # Second call: connection succeeds again
        MockClient.return_value.principal.return_value.calendars.side_effect = None
        MockClient.return_value.principal.return_value.calendars.return_value = [good_cal]
        events = backend.list_events(start, end)

    # Cache was invalidated — a fresh DAVClient was created for the retry
    assert MockClient.call_count == 2
    assert len(events) == 1


def test_task_collections_share_calendar_cache() -> None:
    """list_tasks and list_calendars must share the same cached calendar list."""
    backend = _make_backend()

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = []
        backend.list_calendars()
        backend.list_tasks()

    MockClient.return_value.principal.return_value.calendars.assert_called_once()


def test_nextcloud_task_list_filter_used_for_create_task() -> None:
    cfg = NextcloudConfig(
        name="nc",
        url="https://cloud.example.com",
        username="u",
        password="p",
        task_list_filter="My Tasks",
    )
    backend = NextcloudBackend(cfg)

    tasks_cal = _mock_cal("My Tasks")
    other_cal = _mock_cal("Calendar")

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [
            tasks_cal,
            other_cal,
        ]
        backend.create_task(summary="Nextcloud task")

    tasks_cal.save_event.assert_called_once()
    other_cal.save_event.assert_not_called()


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------


def test_list_tasks() -> None:
    backend = _make_backend()
    cal = _mock_cal("Tasks")
    raw_task = _mock_ical_task(uid="t-1", summary="Buy milk", due=date(2024, 7, 1))
    cal.todos.return_value = [raw_task]

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        tasks = backend.list_tasks()

    assert len(tasks) == 1
    assert isinstance(tasks[0], CalendarTask)
    assert tasks[0].uid == "t-1"
    assert tasks[0].summary == "Buy milk"
    assert tasks[0].due == date(2024, 7, 1)
    assert tasks[0].calendar_name == "Tasks"
    assert tasks[0].backend_name == "test"


def test_list_tasks_handles_error() -> None:
    """Collection that raises should not prevent results from other collections."""
    backend = _make_backend()
    bad_cal = _mock_cal("Bad")
    bad_cal.todos.side_effect = RuntimeError("connection failed")

    good_cal = _mock_cal("Good")
    good_task = _mock_ical_task(uid="t-ok", summary="OK")
    good_cal.todos.return_value = [good_task]

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [bad_cal, good_cal]
        tasks = backend.list_tasks()

    assert len(tasks) == 1
    assert tasks[0].summary == "OK"


def test_list_tasks_calendar_filter() -> None:
    """calendar_name param restricts which collection is queried."""
    backend = _make_backend()
    cal1 = _mock_cal("Personal")
    cal1.todos.return_value = [_mock_ical_task(uid="t-personal", summary="Personal task")]
    cal2 = _mock_cal("Work Tasks")
    cal2.todos.return_value = [_mock_ical_task(uid="t-work", summary="Work task")]

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal1, cal2]
        tasks = backend.list_tasks(calendar_name="Work Tasks")

    cal1.todos.assert_not_called()
    cal2.todos.assert_called_once()
    assert len(tasks) == 1
    assert tasks[0].summary == "Work task"


def test_google_list_tasks_returns_empty() -> None:
    """Google backend must return [] for list_tasks, not raise."""
    cfg = GoogleConfig(name="goog", username="user@gmail.com", password="p")
    backend = GoogleBackend(cfg)

    with patch("mcp_calendar.backends.caldav.DAVClient"):
        result = backend.list_tasks()

    assert result == []


# ---------------------------------------------------------------------------
# CalendarEvent alarms field
# ---------------------------------------------------------------------------


def test_calendar_event_alarms_in_to_dict() -> None:
    event = CalendarEvent(
        uid="uid-1",
        summary="Meeting",
        start=datetime(2024, 6, 5, 10, 0, tzinfo=UTC),
        end=datetime(2024, 6, 5, 11, 0, tzinfo=UTC),
        alarms=[timedelta(minutes=15), timedelta(minutes=30)],
    )
    d = event.to_dict()
    assert d["alarms"] == [15, 30]


def test_calendar_event_default_alarms_empty() -> None:
    event = CalendarEvent(
        uid="uid-1",
        summary="Meeting",
        start=datetime(2024, 6, 5, 10, 0, tzinfo=UTC),
        end=datetime(2024, 6, 5, 11, 0, tzinfo=UTC),
    )
    assert event.to_dict()["alarms"] == []


# ---------------------------------------------------------------------------
# VALARM parsing
# ---------------------------------------------------------------------------


def test_parse_event_reads_valarm() -> None:
    backend = _make_backend()
    raw = _mock_ical_event(alarm_offsets_minutes=[15])
    event = backend._parse_event(raw, "Work")
    assert len(event.alarms) == 1
    assert event.alarms[0] == timedelta(minutes=15)


def test_parse_event_multiple_valarms() -> None:
    backend = _make_backend()
    raw = _mock_ical_event(alarm_offsets_minutes=[5, 15, 30])
    event = backend._parse_event(raw, "Work")
    assert sorted(a.total_seconds() for a in event.alarms) == [
        timedelta(minutes=5).total_seconds(),
        timedelta(minutes=15).total_seconds(),
        timedelta(minutes=30).total_seconds(),
    ]


def test_parse_event_no_valarm_gives_empty_alarms() -> None:
    backend = _make_backend()
    raw = _mock_ical_event()
    event = backend._parse_event(raw, "Work")
    assert event.alarms == []


# ---------------------------------------------------------------------------
# VALARM writing (_build_ical)
# ---------------------------------------------------------------------------


def test_build_ical_with_alarms() -> None:
    backend = _make_backend()
    start = datetime(2024, 7, 1, 9, 0, tzinfo=UTC)
    end = datetime(2024, 7, 1, 10, 0, tzinfo=UTC)
    ical = backend._build_ical("uid-1", "Test", start, end, None, None, [timedelta(minutes=15)])
    assert b"VALARM" in ical
    assert b"TRIGGER" in ical


def test_build_ical_without_alarms_has_no_valarm() -> None:
    backend = _make_backend()
    start = datetime(2024, 7, 1, 9, 0, tzinfo=UTC)
    end = datetime(2024, 7, 1, 10, 0, tzinfo=UTC)
    ical = backend._build_ical("uid-1", "Test", start, end, None, None)
    assert b"VALARM" not in ical


# ---------------------------------------------------------------------------
# create_event with alarms
# ---------------------------------------------------------------------------


def test_create_event_with_alarms() -> None:
    backend = _make_backend()
    cal = _mock_cal("Work")
    start = datetime(2024, 7, 1, 9, 0, tzinfo=UTC)
    end = datetime(2024, 7, 1, 10, 0, tzinfo=UTC)

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        event = backend.create_event(
            summary="Meeting",
            start=start,
            end=end,
            alarms=[timedelta(minutes=15)],
        )

    raw: bytes = cal.save_event.call_args[0][0]
    assert b"VALARM" in raw
    assert event.alarms == [timedelta(minutes=15)]


def test_create_event_without_alarms_no_valarm() -> None:
    backend = _make_backend()
    cal = _mock_cal("Work")
    start = datetime(2024, 7, 1, 9, 0, tzinfo=UTC)
    end = datetime(2024, 7, 1, 10, 0, tzinfo=UTC)

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        event = backend.create_event(summary="Meeting", start=start, end=end)

    raw: bytes = cal.save_event.call_args[0][0]
    assert b"VALARM" not in raw
    assert event.alarms == []


# ---------------------------------------------------------------------------
# update_event alarms
# ---------------------------------------------------------------------------


def test_update_event_preserves_existing_alarms() -> None:
    """Calling update_event without alarms arg must keep the original VALARM."""
    backend = _make_backend()
    cal = _mock_cal("Work")
    uid = "uid-with-alarm"
    raw = _mock_ical_event(uid=uid, alarm_offsets_minutes=[15])
    cal.event_by_uid.return_value = raw

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        updated = backend.update_event(uid=uid, summary="New title")

    assert isinstance(raw.data, str)
    assert "VALARM" in raw.data
    assert updated.alarms == [timedelta(minutes=15)]


def test_update_event_replaces_alarms() -> None:
    """Passing alarms to update_event must replace existing VALARMs."""
    backend = _make_backend()
    cal = _mock_cal("Work")
    uid = "uid-with-alarm"
    raw = _mock_ical_event(uid=uid, alarm_offsets_minutes=[15])
    cal.event_by_uid.return_value = raw

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        updated = backend.update_event(uid=uid, alarms=[timedelta(minutes=5)])

    assert "VALARM" in raw.data
    assert updated.alarms == [timedelta(minutes=5)]


def test_update_event_clears_alarms_with_empty_list() -> None:
    """Passing alarms=[] to update_event must remove all VALARMs."""
    backend = _make_backend()
    cal = _mock_cal("Work")
    uid = "uid-with-alarm"
    raw = _mock_ical_event(uid=uid, alarm_offsets_minutes=[15])
    cal.event_by_uid.return_value = raw

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        updated = backend.update_event(uid=uid, alarms=[])

    assert "VALARM" not in raw.data
    assert updated.alarms == []


def test_update_event_patches_in_place() -> None:
    """update_event must modify existing iCal data, not rebuild from scratch."""
    backend = _make_backend()
    cal = _mock_cal("Work")
    uid = "event-inplace"
    start = datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
    end = datetime(2024, 6, 1, 11, 0, tzinfo=UTC)
    custom_vevent = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        "SUMMARY:Original\r\n"
        "DTSTART:20240601T100000Z\r\n"
        "DTEND:20240601T110000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=5\r\n"
        "X-CUSTOM-PROP:keep-me\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    raw = MagicMock()
    raw.data = custom_vevent
    raw.icalendar_component = _mock_ical_event(
        uid=uid, summary="Original", start=start, end=end
    ).icalendar_component
    cal.event_by_uid.return_value = raw

    with patch("mcp_calendar.backends.caldav.DAVClient") as MockClient:
        MockClient.return_value.principal.return_value.calendars.return_value = [cal]
        backend.update_event(uid=uid, summary="New title")

    assert raw.save.called
    saved_data: str = raw.data
    assert "RRULE" in saved_data
    assert "X-CUSTOM-PROP" in saved_data
    assert "New title" in saved_data
