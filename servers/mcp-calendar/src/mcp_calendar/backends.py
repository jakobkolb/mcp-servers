from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime

import caldav
import icalendar

from .calendar import CalendarBackend, CalendarEvent
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
    ) -> None:
        self.name = name
        self._url = url
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._calendar_filter = calendar_filter

    def _client(self) -> caldav.DAVClient:
        return caldav.DAVClient(
            url=self._url,
            username=self._username,
            password=self._password,
            ssl_verify_cert=self._verify_ssl,
        )

    def _get_calendars(self) -> list[caldav.Calendar]:
        client = self._client()
        calendars: list[caldav.Calendar] = client.principal().calendars()
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

        return CalendarEvent(
            uid=uid,
            summary=summary,
            start=start_dt,
            end=end_dt,
            description=description,
            location=location,
            calendar_name=cal_name,
            backend_name=self.name,
        )

    def _build_ical(
        self,
        uid: str,
        summary: str,
        start: datetime,
        end: datetime,
        description: str | None,
        location: str | None,
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

        cal.add_component(event)
        return cal.to_ical()

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
        ical_bytes = self._build_ical(uid, summary, start, end, description, location)
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
        )

    def update_event(
        self,
        uid: str,
        summary: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> CalendarEvent:
        for cal in self._get_calendars():
            try:
                event = cal.event_by_uid(uid)
            except Exception:
                continue

            comp = event.icalendar_component
            new_summary = summary if summary is not None else str(comp.get("summary", ""))
            dtstart = comp.get("dtstart")
            dtend = comp.get("dtend")
            new_start: datetime
            new_end: datetime

            existing_start = dtstart.dt if dtstart is not None else datetime.now(tz=UTC)
            existing_end = dtend.dt if dtend is not None else datetime.now(tz=UTC)

            # Convert bare date to datetime for the iCal builder
            if not isinstance(existing_start, datetime):
                existing_start = datetime(
                    existing_start.year,
                    existing_start.month,
                    existing_start.day,
                    tzinfo=UTC,
                )
            if not isinstance(existing_end, datetime):
                existing_end = datetime(
                    existing_end.year,
                    existing_end.month,
                    existing_end.day,
                    tzinfo=UTC,
                )

            new_start = start if start is not None else existing_start
            new_end = end if end is not None else existing_end

            existing_desc = comp.get("description")
            new_description = (
                description
                if description is not None
                else (str(existing_desc) if existing_desc is not None else None)
            )
            existing_loc = comp.get("location")
            new_location = (
                location
                if location is not None
                else (str(existing_loc) if existing_loc is not None else None)
            )

            ical_bytes = self._build_ical(
                uid, new_summary, new_start, new_end, new_description, new_location
            )
            event.data = ical_bytes.decode("utf-8")
            event.save()

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
        )
