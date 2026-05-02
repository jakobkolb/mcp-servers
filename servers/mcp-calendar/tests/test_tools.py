"""Tests for calendar MCP tool handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from mcp_calendar import tools
from mcp_calendar.calendar import CalendarEvent
from mcp_calendar.tools import (
    ALL_HANDLERS,
    CreateEventToolHandler,
    DeleteEventToolHandler,
    GetFreeBusyToolHandler,
    ListCalendarsToolHandler,
    ListEventsToolHandler,
    UpdateEventToolHandler,
)


def _text(result: list) -> str:  # type: ignore[type-arg]
    return result[0].text  # type: ignore[no-any-return]


def _make_event(
    uid: str = "uid-1",
    summary: str = "Meeting",
    backend_name: str = "mybackend",
) -> CalendarEvent:
    return CalendarEvent(
        uid=uid,
        summary=summary,
        start=datetime(2024, 6, 5, 10, 0, tzinfo=UTC),
        end=datetime(2024, 6, 5, 11, 0, tzinfo=UTC),
        calendar_name="Work",
        backend_name=backend_name,
    )


def _make_mock_backend(name: str = "mybackend") -> MagicMock:
    backend = MagicMock()
    backend.name = name
    return backend


# ---------------------------------------------------------------------------
# calendar_list_calendars
# ---------------------------------------------------------------------------


def test_list_calendars(mocker: pytest.MonkeyPatch) -> None:
    b1 = _make_mock_backend("icloud")
    b1.list_calendars.return_value = ["Personal", "Work"]
    b2 = _make_mock_backend("google")
    b2.list_calendars.return_value = ["Calendar"]
    mocker.patch.object(tools, "_backends", [b1, b2])

    result = ListCalendarsToolHandler().run_tool({})
    text = _text(result)
    assert "icloud" in text
    assert "Personal" in text
    assert "google" in text


# ---------------------------------------------------------------------------
# calendar_list_events
# ---------------------------------------------------------------------------


def test_list_events_missing_start() -> None:
    with pytest.raises(RuntimeError, match="start"):
        ListEventsToolHandler().run_tool({"end": "2024-06-30T00:00:00"})


def test_list_events_missing_end() -> None:
    with pytest.raises(RuntimeError, match="end"):
        ListEventsToolHandler().run_tool({"start": "2024-06-01T00:00:00"})


def test_list_events(mocker: pytest.MonkeyPatch) -> None:
    b = _make_mock_backend("icloud")
    b.list_events.return_value = [_make_event(uid="e1", summary="Dentist")]
    mocker.patch.object(tools, "_backends", [b])

    result = ListEventsToolHandler().run_tool(
        {"start": "2024-06-01T00:00:00", "end": "2024-06-30T00:00:00"}
    )
    text = _text(result)
    assert "Dentist" in text
    assert "e1" in text


def test_list_events_backend_filter(mocker: pytest.MonkeyPatch) -> None:
    b1 = _make_mock_backend("icloud")
    b1.list_events.return_value = [_make_event(backend_name="icloud")]
    b2 = _make_mock_backend("google")
    b2.list_events.return_value = [_make_event(backend_name="google")]
    mocker.patch.object(tools, "_backends", [b1, b2])

    result = ListEventsToolHandler().run_tool(
        {"start": "2024-06-01T00:00:00", "end": "2024-06-30T00:00:00", "backend": "icloud"}
    )
    b1.list_events.assert_called_once()
    b2.list_events.assert_not_called()
    assert "icloud" in _text(result)


# ---------------------------------------------------------------------------
# calendar_create_event
# ---------------------------------------------------------------------------


def test_create_event_missing_backend() -> None:
    with pytest.raises(RuntimeError, match="backend"):
        CreateEventToolHandler().run_tool(
            {"summary": "X", "start": "2024-06-01T10:00:00", "end": "2024-06-01T11:00:00"}
        )


def test_create_event_missing_summary() -> None:
    with pytest.raises(RuntimeError, match="summary"):
        CreateEventToolHandler().run_tool(
            {"backend": "b", "start": "2024-06-01T10:00:00", "end": "2024-06-01T11:00:00"}
        )


def test_create_event(mocker: pytest.MonkeyPatch) -> None:
    b = _make_mock_backend("icloud")
    created = _make_event(uid="new-uid", summary="Party")
    b.create_event.return_value = created
    mocker.patch.object(tools, "_backends", [b])

    result = CreateEventToolHandler().run_tool(
        {
            "backend": "icloud",
            "summary": "Party",
            "start": "2024-07-04T18:00:00",
            "end": "2024-07-04T22:00:00",
            "description": "Celebration",
        }
    )
    b.create_event.assert_called_once()
    text = _text(result)
    assert "Party" in text
    assert "new-uid" in text


# ---------------------------------------------------------------------------
# calendar_update_event
# ---------------------------------------------------------------------------


def test_update_event_missing_uid() -> None:
    with pytest.raises(RuntimeError, match="uid"):
        UpdateEventToolHandler().run_tool({"backend": "icloud"})


def test_update_event_missing_backend() -> None:
    with pytest.raises(RuntimeError, match="backend"):
        UpdateEventToolHandler().run_tool({"uid": "some-uid"})


def test_update_event(mocker: pytest.MonkeyPatch) -> None:
    b = _make_mock_backend("icloud")
    updated = _make_event(uid="uid-1", summary="Updated title")
    b.update_event.return_value = updated
    mocker.patch.object(tools, "_backends", [b])

    result = UpdateEventToolHandler().run_tool(
        {"uid": "uid-1", "backend": "icloud", "summary": "Updated title"}
    )
    b.update_event.assert_called_once_with(
        uid="uid-1",
        summary="Updated title",
        start=None,
        end=None,
        description=None,
        location=None,
    )
    assert "Updated title" in _text(result)


# ---------------------------------------------------------------------------
# calendar_delete_event
# ---------------------------------------------------------------------------


def test_delete_event_missing_uid() -> None:
    with pytest.raises(RuntimeError, match="uid"):
        DeleteEventToolHandler().run_tool({"backend": "icloud"})


def test_delete_event_missing_backend() -> None:
    with pytest.raises(RuntimeError, match="backend"):
        DeleteEventToolHandler().run_tool({"uid": "some-uid"})


def test_delete_event(mocker: pytest.MonkeyPatch) -> None:
    b = _make_mock_backend("icloud")
    mocker.patch.object(tools, "_backends", [b])

    result = DeleteEventToolHandler().run_tool({"uid": "uid-1", "backend": "icloud"})
    b.delete_event.assert_called_once_with("uid-1")
    assert "uid-1" in _text(result)


# ---------------------------------------------------------------------------
# calendar_get_freebusy
# ---------------------------------------------------------------------------


def test_get_freebusy_missing_start() -> None:
    with pytest.raises(RuntimeError, match="start"):
        GetFreeBusyToolHandler().run_tool({"end": "2024-06-30T00:00:00"})


def test_get_freebusy_missing_end() -> None:
    with pytest.raises(RuntimeError, match="end"):
        GetFreeBusyToolHandler().run_tool({"start": "2024-06-01T00:00:00"})


def test_get_freebusy(mocker: pytest.MonkeyPatch) -> None:
    b = _make_mock_backend("icloud")
    slot_start = datetime(2024, 6, 5, 10, 0, tzinfo=UTC)
    slot_end = datetime(2024, 6, 5, 11, 0, tzinfo=UTC)
    b.get_freebusy.return_value = [(slot_start, slot_end)]
    mocker.patch.object(tools, "_backends", [b])

    result = GetFreeBusyToolHandler().run_tool(
        {"start": "2024-06-01T00:00:00", "end": "2024-06-30T00:00:00"}
    )
    text = _text(result)
    assert "icloud" in text
    assert "2024-06-05" in text


def test_get_freebusy_backend_filter(mocker: pytest.MonkeyPatch) -> None:
    b1 = _make_mock_backend("icloud")
    b1.get_freebusy.return_value = []
    b2 = _make_mock_backend("google")
    b2.get_freebusy.return_value = []
    mocker.patch.object(tools, "_backends", [b1, b2])

    GetFreeBusyToolHandler().run_tool(
        {"start": "2024-06-01T00:00:00", "end": "2024-06-30T00:00:00", "backend": "icloud"}
    )
    b1.get_freebusy.assert_called_once()
    b2.get_freebusy.assert_not_called()


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------


def test_all_handlers_registered() -> None:
    assert len(ALL_HANDLERS) == 6


def test_all_handlers_have_descriptions() -> None:
    for handler in ALL_HANDLERS:
        desc = handler.get_tool_description()
        assert desc.name
        assert desc.description
        assert desc.inputSchema
