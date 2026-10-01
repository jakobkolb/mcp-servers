from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta
from typing import cast

import caldav
import icalendar
import recurring_ical_events

from .calendar import (
    CalendarBackend,
    CalendarEvent,
    CalendarTask,
    UnsupportedOperationError,
    localize,
)
from .config import GoogleConfig, ICloudConfig, NextcloudConfig

logger = logging.getLogger(__name__)


def _set(comp: icalendar.Component, **props: object) -> None:
    """Replace each given property on comp; None leaves it untouched. Times are localized."""
    for key, value in props.items():
        if value is None:
            continue
        comp.pop(key, None)
        comp.add(key, localize(value) if isinstance(value, date) else value)


def _validate(summary: str | None, start: datetime | date, end: datetime | date) -> None:
    if summary is not None and not summary.strip():
        raise ValueError("summary must not be empty")
    if isinstance(start, datetime) != isinstance(end, datetime):
        raise ValueError("start and end must both be dates (all-day) or both datetimes")
    if localize(end) <= localize(start):
        raise ValueError(f"end ({end.isoformat()}) must be after start ({start.isoformat()})")


def _set_alarms(event: icalendar.Event, alarms: list[timedelta]) -> None:
    event.subcomponents = [c for c in event.subcomponents if c.name != "VALARM"]
    for offset in alarms:
        alarm = icalendar.Alarm()
        alarm.add("ACTION", "DISPLAY")
        alarm.add("DESCRIPTION", "Reminder")
        alarm.add("TRIGGER", -offset)
        event.add_component(alarm)


def _master(cal: icalendar.Calendar) -> icalendar.Event:
    return next((e for e in cal.events if "RECURRENCE-ID" not in e), cal.events[0])


def _detach_instance(cal: icalendar.Calendar, recurrence_id: datetime | date) -> icalendar.Event:
    """Turn one instance of a series into a standalone override component and return it.

    The expanded occurrence already merges the master with any existing override, so it
    replaces that override (if any) as-is.
    """
    occurrences = recurring_ical_events.of(cal).between(
        recurrence_id, recurrence_id + timedelta(days=1)
    )
    instance = next(
        (o for o in occurrences if localize(o["RECURRENCE-ID"].dt) == localize(recurrence_id)),
        None,
    )
    if instance is None:
        raise ValueError(f"Series has no instance at {recurrence_id.isoformat()}")
    rid = instance["RECURRENCE-ID"].dt
    cal.subcomponents = [
        c for c in cal.subcomponents if not ("RECURRENCE-ID" in c and c["RECURRENCE-ID"].dt == rid)
    ]
    cal.add_component(instance)
    return instance


def _to_ical(cal: icalendar.Calendar) -> str:
    cal.add_missing_timezones()
    return cal.to_ical().decode("utf-8")


def _new_calendar(comp: icalendar.Component) -> str:
    cal = icalendar.Calendar()
    cal.add("prodid", "-//mcp-calendar//EN")
    cal.add("version", "2.0")
    comp.add("uid", str(uuid.uuid4()))
    cal.add_component(comp)
    return _to_ical(cal)


class CaldavBackend(CalendarBackend):
    """Shared CalDAV implementation used by all three backend subclasses."""

    _url: str
    _username: str
    _password: str
    _verify_ssl: bool
    _calendar_filter: str | None

    def __init__(
        self,
        name: str,
        url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        calendar_filter: str | None = None,
        task_filter: str | None = None,
    ) -> None:
        self.name = name
        self._url = url
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._calendar_filter = calendar_filter
        self._task_filter = task_filter
        self._cached_client: caldav.DAVClient | None = None
        self._cached_all_calendars: list[caldav.Calendar] | None = None

    def _client(self) -> caldav.DAVClient:
        if self._cached_client is None:
            self._cached_client = caldav.DAVClient(
                url=self._url,
                username=self._username,
                password=self._password,
                ssl_verify_cert=self._verify_ssl,
            )
        return self._cached_client

    def _all_calendars(self) -> list[caldav.Calendar]:
        if self._cached_all_calendars is None:
            try:
                self._cached_all_calendars = self._client().principal().calendars()
            except Exception:
                self._cached_client = None
                self._cached_all_calendars = None
                raise
        return self._cached_all_calendars

    def _get_task_collections(self) -> list[caldav.Calendar]:
        collections = self._all_calendars()
        filter_name = self._task_filter if self._task_filter is not None else self._calendar_filter
        if filter_name is not None:
            collections = [c for c in collections if c.name == filter_name]
        vtodo_collections: list[caldav.Calendar] = []
        for col in collections:
            try:
                if "VTODO" in col.get_supported_components():
                    vtodo_collections.append(col)
            except Exception:
                vtodo_collections.append(col)  # include if we can't determine; fail later
        return vtodo_collections

    def _get_calendars(self) -> list[caldav.Calendar]:
        calendars = self._all_calendars()
        if self._calendar_filter is not None:
            calendars = [c for c in calendars if c.name == self._calendar_filter]
        return calendars

    def _parse_event(self, comp: icalendar.Event, cal_name: str) -> CalendarEvent:
        description = comp.get("description")
        location = comp.get("location")
        triggers = [a["TRIGGER"].dt for a in comp.walk("VALARM") if "TRIGGER" in a]
        return CalendarEvent(
            uid=str(comp.get("uid", "")),
            summary=str(comp.get("summary", "")),
            start=localize(comp.start),
            end=localize(comp.end),  # derives a missing DTEND from DURATION or RFC 5545 defaults
            description=str(description) if description is not None else None,
            location=str(location) if location is not None else None,
            calendar_name=cal_name,
            backend_name=self.name,
            alarms=[abs(t) for t in triggers if isinstance(t, timedelta)],
            transparent=comp.get("transp") == "TRANSPARENT",
            recurrence_id=localize(comp["RECURRENCE-ID"].dt) if "RECURRENCE-ID" in comp else None,
        )

    def _parse_task(self, comp: icalendar.Todo, cal_name: str) -> CalendarTask:
        description = comp.get("description")
        due = comp.get("due")
        return CalendarTask(
            uid=str(comp.get("uid", "")),
            summary=str(comp.get("summary", "")),
            description=str(description) if description is not None else None,
            due=localize(due.dt) if due is not None else None,
            priority=int(comp.get("priority", 0)),
            status=str(comp.get("status", "NEEDS-ACTION")),
            calendar_name=cal_name,
            backend_name=self.name,
        )

    def _find_event_by_uid(self, cal: caldav.Calendar, uid: str) -> caldav.CalendarObjectResource:
        """Look up an event by UID, falling back to a client-side scan.

        Some CalDAV servers (notably iCloud) don't reliably support the
        UID REPORT query that event_by_uid() relies on server-side.
        """
        try:
            return cal.event_by_uid(uid)
        except Exception:
            for event in cal.events():
                if str(event.icalendar_component.get("uid", "")) == uid:
                    return event
            raise

    def _find_task_by_uid(self, col: caldav.Calendar, uid: str) -> caldav.CalendarObjectResource:
        """Look up a task by UID, falling back to a client-side scan.

        Some CalDAV servers (notably iCloud) don't reliably support the
        UID REPORT query that get_todo_by_uid() relies on server-side.
        """
        try:
            return col.get_todo_by_uid(uid)
        except Exception:
            for task in col.todos(include_completed=True):
                if str(task.icalendar_component.get("uid", "")) == uid:
                    return task
            raise

    def list_calendars(self) -> list[str]:
        return [c.name for c in self._get_calendars()]

    def list_events(
        self, start: datetime, end: datetime, calendar_name: str | None = None
    ) -> list[CalendarEvent]:
        start, end = localize(start), localize(end)
        events: list[CalendarEvent] = []
        for cal in self._get_calendars():
            if calendar_name is not None and cal.name != calendar_name:
                continue
            try:
                cal_name: str = cal.name or ""
                # Expand client-side: caldav's expansion keeps replaced instances and
                # filters by start time only; this one applies overrides and overlap.
                for obj in cal.search(start=start, end=end, event=True, expand=False):
                    try:
                        series = obj.icalendar_instance
                        recurring = any("RRULE" in e or "RDATE" in e for e in series.events)
                        for occurrence in recurring_ical_events.of(series).between(start, end):
                            event = self._parse_event(occurrence, cal_name)
                            if not recurring:
                                event.recurrence_id = None
                            events.append(event)
                    except Exception:
                        logger.exception("Failed to parse event in calendar %s", cal_name)
            except Exception:
                logger.exception("Failed to search calendar %s", getattr(cal, "name", "?"))
        return events

    def create_event(
        self,
        summary: str,
        start: datetime | date,
        end: datetime | date,
        calendar_name: str | None = None,
        description: str | None = None,
        location: str | None = None,
        alarms: list[timedelta] | None = None,
        rrule: str | None = None,
    ) -> CalendarEvent:
        _validate(summary, start, end)
        calendars = self._get_calendars()
        if calendar_name is not None:
            target = next((c for c in calendars if c.name == calendar_name), None)
            if target is None:
                raise ValueError(f"Calendar '{calendar_name}' not found")
        else:
            if not calendars:
                raise ValueError("No calendars available")
            target = calendars[0]

        event = icalendar.Event()
        _set(
            event,
            summary=summary,
            dtstart=start,
            dtend=end,
            description=description,
            location=location,
        )
        _set_alarms(event, alarms or [])
        if rrule is not None:
            event.add("rrule", icalendar.vRecur.from_ical(rrule))
        target.save_event(_new_calendar(event))
        return self._parse_event(event, target.name or "")

    def update_event(
        self,
        uid: str,
        summary: str | None = None,
        start: datetime | date | None = None,
        end: datetime | date | None = None,
        description: str | None = None,
        location: str | None = None,
        alarms: list[timedelta] | None = None,
        recurrence_id: datetime | date | None = None,
    ) -> CalendarEvent:
        for cal in self._get_calendars():
            try:
                event = self._find_event_by_uid(cal, uid)
            except Exception:
                continue

            # Patch in-place to preserve custom properties (RRULE, ATTENDEE, etc.)
            raw_cal = icalendar.Calendar.from_ical(event.data)
            if recurrence_id is not None:
                vevent = _detach_instance(raw_cal, recurrence_id)
            else:
                vevent = _master(raw_cal)
            if (start is not None or end is not None) and "RRULE" in vevent:
                # Rewriting DTSTART of a master re-anchors the whole series and drops
                # the instances before it.
                raise ValueError(
                    f"Event '{uid}' is recurring; changing its start/end would move the whole "
                    "series. Pass recurrence_id to move a single instance."
                )
            if start is not None and end is None:
                end = start + (vevent.end - vevent.start)  # move, keeping the duration
            _validate(summary, start or vevent.start, end or vevent.end)
            _set(
                vevent,
                summary=summary,
                dtstart=start,
                dtend=end,
                description=description,
                location=location,
            )
            if alarms is not None:
                _set_alarms(vevent, alarms)
            event.data = _to_ical(raw_cal)
            event.save()
            return self._parse_event(vevent, getattr(cal, "name", "") or "")

        raise ValueError(f"Event with uid '{uid}' not found in backend '{self.name}'")

    def delete_event(self, uid: str, recurrence_id: datetime | date | None = None) -> None:
        for cal in self._get_calendars():
            try:
                event = self._find_event_by_uid(cal, uid)
            except Exception:
                continue
            if recurrence_id is None:
                event.delete()
                return
            raw_cal = icalendar.Calendar.from_ical(event.data)
            instance = _detach_instance(raw_cal, recurrence_id)
            raw_cal.subcomponents.remove(instance)
            _master(raw_cal).add("exdate", instance["RECURRENCE-ID"].dt)
            event.data = _to_ical(raw_cal)
            event.save()
            return
        raise ValueError(f"Event with uid '{uid}' not found in backend '{self.name}'")

    def create_task(
        self,
        summary: str,
        calendar_name: str | None = None,
        description: str | None = None,
        due: date | datetime | None = None,
        priority: int = 0,
    ) -> CalendarTask:
        collections = self._get_task_collections()
        if calendar_name is not None:
            target = next((c for c in collections if c.name == calendar_name), None)
            if target is None:
                if calendar_name in self.list_calendars():
                    raise ValueError(f"Calendar '{calendar_name}' does not support tasks")
                raise ValueError(f"Calendar '{calendar_name}' not found")
        else:
            if not collections:
                raise ValueError("No task collections available")
            target = collections[0]

        todo = icalendar.Todo()
        _set(
            todo,
            summary=summary,
            description=description,
            due=due,
            priority=priority,
            status="NEEDS-ACTION",
        )
        target.save_event(_new_calendar(todo))
        return self._parse_task(todo, target.name or "")

    def update_task(
        self,
        uid: str,
        summary: str | None = None,
        description: str | None = None,
        due: date | datetime | None = None,
        priority: int | None = None,
        status: str | None = None,
    ) -> CalendarTask:
        for col in self._get_task_collections():
            try:
                task_obj = self._find_task_by_uid(col, uid)
            except Exception:
                continue

            # Parse and patch in-place to preserve any custom properties
            raw_cal = icalendar.Calendar.from_ical(task_obj.data)
            vtodo = next(c for c in raw_cal.walk() if c.name == "VTODO")

            _set(
                vtodo,
                summary=summary,
                description=description,
                due=due,
                priority=priority,
                status=status,
            )
            task_obj.data = _to_ical(raw_cal)
            task_obj.save()
            return self._parse_task(vtodo, getattr(col, "name", "") or "")

        raise ValueError(f"Task with uid '{uid}' not found in backend '{self.name}'")

    def delete_task(self, uid: str) -> None:
        for col in self._get_task_collections():
            try:
                task_obj = self._find_task_by_uid(col, uid)
                task_obj.delete()
                return
            except Exception:
                continue
        raise ValueError(f"Task with uid '{uid}' not found in backend '{self.name}'")

    def list_tasks(
        self, calendar_name: str | None = None, include_completed: bool = False
    ) -> list[CalendarTask]:
        tasks: list[CalendarTask] = []
        collections = self._get_task_collections()
        if calendar_name is not None:
            collections = [c for c in collections if c.name == calendar_name]
        for col in collections:
            try:
                col_name: str = col.name or ""
                for obj in col.todos(include_completed=include_completed):
                    try:
                        tasks.append(self._parse_task(obj.icalendar_component, col_name))
                    except Exception:
                        logger.exception("Failed to parse task in collection %s", col_name)
            except Exception:
                logger.exception("Failed to list tasks in collection %s", getattr(col, "name", "?"))
        return tasks

    def get_freebusy(
        self, start: datetime, end: datetime, calendar_name: str | None = None
    ) -> list[tuple[datetime, datetime]]:
        def as_datetime(value: datetime | date) -> datetime:
            # All-day dates become local midnight; datetimes are already localized.
            if isinstance(value, datetime):
                return value
            return cast(datetime, localize(datetime.combine(value, time())))

        busy = sorted(
            (as_datetime(ev.start), as_datetime(ev.end))
            for ev in self.list_events(start, end, calendar_name)
            if not ev.transparent
        )
        merged: list[tuple[datetime, datetime]] = []
        for slot_start, slot_end in busy:
            if merged and slot_start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], slot_end))
            else:
                merged.append((slot_start, slot_end))
        return merged


class ICloudBackend(CaldavBackend):
    def __init__(self, cfg: ICloudConfig) -> None:
        super().__init__(
            name=cfg.name,
            url="https://caldav.icloud.com/",
            username=cfg.username,
            password=cfg.password,
        )


class GoogleBackend(CaldavBackend):
    def __init__(self, cfg: GoogleConfig) -> None:
        url = f"https://apidata.googleusercontent.com/caldav/v2/{cfg.username}/user"
        super().__init__(
            name=cfg.name,
            url=url,
            username=cfg.username,
            password=cfg.password,
        )

    def list_tasks(
        self, calendar_name: str | None = None, include_completed: bool = False
    ) -> list[CalendarTask]:
        return []

    def create_task(self, summary: str, **kwargs: object) -> CalendarTask:  # type: ignore[override]
        raise UnsupportedOperationError("Google CalDAV does not support VTODO write operations")

    def update_task(self, uid: str, **kwargs: object) -> CalendarTask:  # type: ignore[override]
        raise UnsupportedOperationError("Google CalDAV does not support VTODO write operations")

    def delete_task(self, uid: str) -> None:
        raise UnsupportedOperationError("Google CalDAV does not support VTODO write operations")


class NextcloudBackend(CaldavBackend):
    def __init__(self, cfg: NextcloudConfig) -> None:
        url = f"{cfg.url.rstrip('/')}/remote.php/dav/"
        super().__init__(
            name=cfg.name,
            url=url,
            username=cfg.username,
            password=cfg.password,
            verify_ssl=cfg.verify_ssl,
            calendar_filter=cfg.calendar_name,
            task_filter=cfg.task_list_filter,
        )
