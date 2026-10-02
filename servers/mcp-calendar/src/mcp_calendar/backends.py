from __future__ import annotations

import copy
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import caldav
import icalendar
from dateutil.rrule import rrulestr

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


def _set_alarms(event: icalendar.Event, alarms: list[timedelta]) -> None:
    event.subcomponents = [c for c in event.subcomponents if c.name != "VALARM"]
    for offset in alarms:
        alarm = icalendar.Alarm()
        alarm.add("ACTION", "DISPLAY")
        alarm.add("DESCRIPTION", "Reminder")
        alarm.add("TRIGGER", -offset)
        event.add_component(alarm)


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
        dtstart = comp.get("dtstart")
        dtend = comp.get("dtend")
        return CalendarEvent(
            uid=str(comp.get("uid", "")),
            summary=str(comp.get("summary", "")),
            start=localize(dtstart.dt) if dtstart is not None else datetime.now(tz=UTC),
            end=localize(dtend.dt) if dtend is not None else datetime.now(tz=UTC),
            description=str(description) if description is not None else None,
            location=str(location) if location is not None else None,
            calendar_name=cal_name,
            backend_name=self.name,
            alarms=[abs(t) for t in triggers if isinstance(t, timedelta)],
        )

    def _expand_occurrences(
        self, caldav_event: caldav.Event, start: datetime, end: datetime
    ) -> list[Any]:
        """Return one VEVENT component per occurrence of caldav_event within [start, end].

        caldav's own RRULE expansion (server-side or client-side, depending on the
        backend) has been observed to silently drop occurrences for weekly recurring
        events (see issue #70). Expand RRULE + EXDATE ourselves instead of trusting it.
        """
        raw_cal = icalendar.Calendar.from_ical(caldav_event.data)
        vevents = [c for c in raw_cal.walk() if c.name == "VEVENT"]
        master = next((v for v in vevents if v.get("RRULE") is not None), None)
        if master is None:
            return vevents

        overrides = [v for v in vevents if v is not master]
        return overrides + self._expand_rrule(master, start, end)

    def _expand_rrule(self, master: Any, start: datetime, end: datetime) -> list[Any]:
        dtstart = master["DTSTART"].dt
        all_day = not isinstance(dtstart, datetime)
        dtstart_dt = datetime(dtstart.year, dtstart.month, dtstart.day) if all_day else dtstart

        dtend_prop = master.get("DTEND")
        duration = (dtend_prop.dt - dtstart) if dtend_prop is not None else timedelta(0)

        if all_day:
            # rule occurrences are naive midnight datetimes; compare against naive bounds
            range_start = datetime(start.year, start.month, start.day)
            range_end = datetime(end.year, end.month, end.day)
        elif dtstart_dt.tzinfo is not None:
            range_start = start if start.tzinfo is not None else start.replace(tzinfo=UTC)
            range_end = end if end.tzinfo is not None else end.replace(tzinfo=UTC)
        else:
            range_start = start.replace(tzinfo=None)
            range_end = end.replace(tzinfo=None)

        exdates: set[Any] = set()
        exdate_prop = master.get("EXDATE")
        if exdate_prop is not None:
            items = exdate_prop if isinstance(exdate_prop, list) else [exdate_prop]
            for item in items:
                exdates.update(d.dt for d in item.dts)

        rule = rrulestr(master["RRULE"].to_ical().decode(), dtstart=dtstart_dt)

        occurrences = []
        for occ_dt in rule.between(range_start, range_end, inc=True):
            occ_value = occ_dt.date() if all_day else occ_dt
            if occ_value in exdates:
                continue
            occ = copy.deepcopy(master)
            del occ["DTSTART"]
            occ.add("DTSTART", occ_value)
            if "DTEND" in occ:
                del occ["DTEND"]
                occ.add("DTEND", occ_value + duration)
            occurrences.append(occ)
        return occurrences

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
            for task in col.todos():
                if str(task.icalendar_component.get("uid", "")) == uid:
                    return task
            raise

    def list_calendars(self) -> list[str]:
        return [c.name for c in self._get_calendars()]

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        start, end = localize(start), localize(end)
        events: list[CalendarEvent] = []
        for cal in self._get_calendars():
            try:
                cal_name: str = cal.name or ""
                # expand=False: recurrences are expanded ourselves in _expand_occurrences,
                # since caldav's own RRULE expansion has been observed to drop occurrences.
                raw_events = cal.date_search(start=start, end=end, expand=False)
                for e in raw_events:
                    try:
                        for comp in self._expand_occurrences(e, start, end):
                            events.append(self._parse_event(comp, cal_name))
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
    ) -> CalendarEvent:
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
    ) -> CalendarEvent:
        for cal in self._get_calendars():
            try:
                event = self._find_event_by_uid(cal, uid)
            except Exception:
                continue

            # Patch in-place to preserve custom properties (RRULE, ATTENDEE, etc.)
            raw_cal = icalendar.Calendar.from_ical(event.data)
            vevent = raw_cal.events[0]
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

        raise ValueError(f"Event with uid '{uid}' not found in any calendar")

    def delete_event(self, uid: str) -> None:
        for cal in self._get_calendars():
            try:
                event = self._find_event_by_uid(cal, uid)
                event.delete()
                return
            except Exception:
                continue
        raise ValueError(f"Event with uid '{uid}' not found in any calendar")

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

            final_summary = summary if summary is not None else str(vtodo.get("SUMMARY", ""))
            existing_status = str(vtodo.get("STATUS", "NEEDS-ACTION"))
            final_status = status if status is not None else existing_status
            return CalendarTask(
                uid=uid,
                summary=final_summary,
                description=description,
                due=due,
                priority=priority if priority is not None else 0,
                status=final_status,
                calendar_name=getattr(col, "name", "") or "",
                backend_name=self.name,
            )

        raise ValueError(f"Task with uid '{uid}' not found in any collection")

    def delete_task(self, uid: str) -> None:
        for col in self._get_task_collections():
            try:
                task_obj = self._find_task_by_uid(col, uid)
                task_obj.delete()
                return
            except Exception:
                continue
        raise ValueError(f"Task with uid '{uid}' not found in any collection")

    def list_tasks(self, calendar_name: str | None = None) -> list[CalendarTask]:
        tasks: list[CalendarTask] = []
        collections = self._get_task_collections()
        if calendar_name is not None:
            collections = [c for c in collections if c.name == calendar_name]
        for col in collections:
            try:
                col_name: str = col.name or ""
                for obj in col.todos():
                    try:
                        tasks.append(self._parse_task(obj.icalendar_component, col_name))
                    except Exception:
                        logger.exception("Failed to parse task in collection %s", col_name)
            except Exception:
                logger.exception("Failed to list tasks in collection %s", getattr(col, "name", "?"))
        return tasks

    def get_freebusy(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        events = self.list_events(start, end)
        result: list[tuple[datetime, datetime]] = []
        for ev in events:
            ev_start = ev.start
            ev_end = ev.end
            if not isinstance(ev_start, datetime):
                ev_start = datetime(ev_start.year, ev_start.month, ev_start.day, tzinfo=UTC)
            if not isinstance(ev_end, datetime):
                ev_end = datetime(ev_end.year, ev_end.month, ev_end.day, tzinfo=UTC)
            result.append((ev_start, ev_end))
        return result


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

    def list_tasks(self, calendar_name: str | None = None) -> list[CalendarTask]:
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
