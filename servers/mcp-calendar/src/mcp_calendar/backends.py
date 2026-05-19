from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta

import caldav
import icalendar

from .calendar import CalendarBackend, CalendarEvent, CalendarTask, UnsupportedOperationError
from .config import GoogleConfig, ICloudConfig, NextcloudConfig

logger = logging.getLogger(__name__)


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
        return collections

    def _get_calendars(self) -> list[caldav.Calendar]:
        calendars = self._all_calendars()
        if self._calendar_filter is not None:
            calendars = [c for c in calendars if c.name == self._calendar_filter]
        return calendars

    def _parse_event(self, caldav_event: caldav.Event, cal_name: str) -> CalendarEvent:
        comp = caldav_event.icalendar_component
        uid = str(comp.get("uid", ""))
        summary = str(comp.get("summary", ""))
        description_prop = comp.get("description")
        description = str(description_prop) if description_prop is not None else None
        location_prop = comp.get("location")
        location = str(location_prop) if location_prop is not None else None

        dtstart = comp.get("dtstart")
        dtend = comp.get("dtend")

        start_dt: datetime | date = dtstart.dt if dtstart is not None else datetime.now(tz=UTC)
        end_dt: datetime | date = dtend.dt if dtend is not None else datetime.now(tz=UTC)

        alarms: list[timedelta] = []
        for sub in comp.walk():
            if sub.name == "VALARM":
                trigger = sub.get("TRIGGER")
                if trigger is not None and isinstance(trigger.dt, timedelta):
                    alarms.append(abs(trigger.dt))

        return CalendarEvent(
            uid=uid,
            summary=summary,
            start=start_dt,
            end=end_dt,
            description=description,
            location=location,
            calendar_name=cal_name,
            backend_name=self.name,
            alarms=alarms,
        )

    def _build_ical(
        self,
        uid: str,
        summary: str,
        start: datetime,
        end: datetime,
        description: str | None,
        location: str | None,
        alarms: list[timedelta] | None = None,
    ) -> bytes:
        cal = icalendar.Calendar()
        cal.add("prodid", "-//mcp-calendar//EN")
        cal.add("version", "2.0")

        event = icalendar.Event()
        event.add("uid", uid)
        event.add("summary", summary)
        event.add("dtstart", start)
        event.add("dtend", end)
        if description is not None:
            event.add("description", description)
        if location is not None:
            event.add("location", location)
        for offset in alarms or []:
            alarm = icalendar.Alarm()
            alarm.add("ACTION", "DISPLAY")
            alarm.add("DESCRIPTION", "Reminder")
            alarm.add("TRIGGER", -offset)
            event.add_component(alarm)

        cal.add_component(event)
        return cal.to_ical()

    def _build_vtodo(
        self,
        uid: str,
        summary: str,
        description: str | None,
        due: date | datetime | None,
        priority: int,
    ) -> bytes:
        cal = icalendar.Calendar()
        cal.add("prodid", "-//mcp-calendar//EN")
        cal.add("version", "2.0")

        todo = icalendar.Todo()
        todo.add("uid", uid)
        todo.add("summary", summary)
        todo.add("priority", priority)
        todo.add("status", "NEEDS-ACTION")
        if description is not None:
            todo.add("description", description)
        if due is not None:
            todo.add("due", due)

        cal.add_component(todo)
        return cal.to_ical()

    def _parse_task(self, caldav_obj: caldav.CalendarObjectResource, cal_name: str) -> CalendarTask:
        comp = caldav_obj.icalendar_component
        uid = str(comp.get("uid", ""))
        summary = str(comp.get("summary", ""))
        desc_prop = comp.get("description")
        description = str(desc_prop) if desc_prop is not None else None
        due_prop = comp.get("due")
        due: date | datetime | None = due_prop.dt if due_prop is not None else None
        priority_prop = comp.get("priority")
        priority = int(priority_prop) if priority_prop is not None else 0
        status_prop = comp.get("status")
        status = str(status_prop) if status_prop is not None else "NEEDS-ACTION"
        return CalendarTask(
            uid=uid,
            summary=summary,
            description=description,
            due=due,
            priority=priority,
            status=status,
            calendar_name=cal_name,
            backend_name=self.name,
        )

    def list_calendars(self) -> list[str]:
        return [c.name for c in self._get_calendars()]

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for cal in self._get_calendars():
            try:
                cal_name: str = cal.name or ""
                raw_events = cal.date_search(start=start, end=end, expand=True)
                for e in raw_events:
                    try:
                        events.append(self._parse_event(e, cal_name))
                    except Exception:
                        logger.exception("Failed to parse event in calendar %s", cal_name)
            except Exception:
                logger.exception("Failed to search calendar %s", getattr(cal, "name", "?"))
        return events

    def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
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

        uid = str(uuid.uuid4())
        ical_bytes = self._build_ical(uid, summary, start, end, description, location, alarms)
        target.save_event(ical_bytes)

        return CalendarEvent(
            uid=uid,
            summary=summary,
            start=start,
            end=end,
            description=description,
            location=location,
            calendar_name=target.name or "",
            backend_name=self.name,
            alarms=alarms or [],
        )

    def update_event(
        self,
        uid: str,
        summary: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
        alarms: list[timedelta] | None = None,
    ) -> CalendarEvent:
        for cal in self._get_calendars():
            try:
                event = cal.event_by_uid(uid)
            except Exception:
                continue

            # Patch in-place to preserve custom properties (RRULE, ATTENDEE, etc.)
            raw_cal = icalendar.Calendar.from_ical(event.data)
            vevent = next(c for c in raw_cal.walk() if c.name == "VEVENT")

            if summary is not None:
                del vevent["SUMMARY"]
                vevent.add("SUMMARY", summary)
            if start is not None:
                del vevent["DTSTART"]
                vevent.add("DTSTART", start)
            if end is not None:
                del vevent["DTEND"]
                vevent.add("DTEND", end)
            if description is not None:
                if "DESCRIPTION" in vevent:
                    del vevent["DESCRIPTION"]
                vevent.add("DESCRIPTION", description)
            if location is not None:
                if "LOCATION" in vevent:
                    del vevent["LOCATION"]
                vevent.add("LOCATION", location)
            if alarms is not None:
                vevent.subcomponents = [c for c in vevent.subcomponents if c.name != "VALARM"]
                for offset in alarms:
                    alarm = icalendar.Alarm()
                    alarm.add("ACTION", "DISPLAY")
                    alarm.add("DESCRIPTION", "Reminder")
                    alarm.add("TRIGGER", -offset)
                    vevent.add_component(alarm)

            event.data = raw_cal.to_ical().decode("utf-8")
            event.save()

            new_summary = str(vevent.get("SUMMARY", ""))
            dtstart = vevent.get("DTSTART")
            dtend = vevent.get("DTEND")
            new_start: datetime | date = dtstart.dt if dtstart is not None else datetime.now(tz=UTC)
            new_end: datetime | date = dtend.dt if dtend is not None else datetime.now(tz=UTC)
            desc_prop = vevent.get("DESCRIPTION")
            new_description = str(desc_prop) if desc_prop is not None else None
            loc_prop = vevent.get("LOCATION")
            new_location = str(loc_prop) if loc_prop is not None else None
            new_alarms: list[timedelta] = []
            for sub in vevent.subcomponents:
                if sub.name == "VALARM":
                    trigger = sub.get("TRIGGER")
                    if trigger is not None and isinstance(trigger.dt, timedelta):
                        new_alarms.append(abs(trigger.dt))

            cal_name: str = getattr(cal, "name", "") or ""
            return CalendarEvent(
                uid=uid,
                summary=new_summary,
                start=new_start,
                end=new_end,
                description=new_description,
                location=new_location,
                calendar_name=cal_name,
                backend_name=self.name,
                alarms=new_alarms,
            )

        raise ValueError(f"Event with uid '{uid}' not found in any calendar")

    def delete_event(self, uid: str) -> None:
        for cal in self._get_calendars():
            try:
                event = cal.event_by_uid(uid)
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

        uid = str(uuid.uuid4())
        ical_bytes = self._build_vtodo(uid, summary, description, due, priority)
        target.save_event(ical_bytes)

        return CalendarTask(
            uid=uid,
            summary=summary,
            description=description,
            due=due,
            priority=priority,
            status="NEEDS-ACTION",
            calendar_name=target.name or "",
            backend_name=self.name,
        )

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
                task_obj = col.event_by_uid(uid)
            except Exception:
                continue

            # Parse and patch in-place to preserve any custom properties
            raw_cal = icalendar.Calendar.from_ical(task_obj.data)
            vtodo = next(c for c in raw_cal.walk() if c.name == "VTODO")

            if summary is not None:
                del vtodo["SUMMARY"]
                vtodo.add("SUMMARY", summary)
            if description is not None:
                if "DESCRIPTION" in vtodo:
                    del vtodo["DESCRIPTION"]
                vtodo.add("DESCRIPTION", description)
            if due is not None:
                if "DUE" in vtodo:
                    del vtodo["DUE"]
                vtodo.add("DUE", due)
            if priority is not None:
                if "PRIORITY" in vtodo:
                    del vtodo["PRIORITY"]
                vtodo.add("PRIORITY", priority)
            if status is not None:
                if "STATUS" in vtodo:
                    del vtodo["STATUS"]
                vtodo.add("STATUS", status)

            task_obj.data = raw_cal.to_ical().decode("utf-8")
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
                task_obj = col.event_by_uid(uid)
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
                        tasks.append(self._parse_task(obj, col_name))
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
