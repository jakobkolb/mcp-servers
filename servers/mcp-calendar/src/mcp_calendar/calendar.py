import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# Floating/naive times are read as this zone; all times are written and returned in it.
TZ = ZoneInfo(os.environ.get("CALENDAR_TZ", "UTC"))


def localize(value: datetime | date) -> datetime | date:
    if not isinstance(value, datetime):
        return value
    return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)


class UnsupportedOperationError(Exception):
    """Raised when a backend does not support the requested operation."""


@dataclass
class CalendarEvent:
    uid: str
    summary: str
    start: datetime | date
    end: datetime | date
    description: str | None = None
    location: str | None = None
    calendar_name: str = ""
    backend_name: str = ""
    alarms: list[timedelta] = field(default_factory=list)
    transparent: bool = False  # TRANSP:TRANSPARENT, i.e. doesn't block time
    recurrence_id: datetime | date | None = None  # set only for instances of a series

    def to_dict(self) -> dict[str, object]:
        return {
            "uid": self.uid,
            "summary": self.summary,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "description": self.description,
            "location": self.location,
            "calendar_name": self.calendar_name,
            "backend_name": self.backend_name,
            "alarms": [int(a.total_seconds() / 60) for a in self.alarms],
            "recurrence_id": self.recurrence_id.isoformat() if self.recurrence_id else None,
        }


@dataclass
class CalendarTask:
    uid: str
    summary: str
    description: str | None = None
    due: date | datetime | None = None
    priority: int = 0
    status: str = "NEEDS-ACTION"
    calendar_name: str = ""
    backend_name: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "uid": self.uid,
            "summary": self.summary,
            "description": self.description,
            "due": self.due.isoformat() if self.due is not None else None,
            "priority": self.priority,
            "status": self.status,
            "calendar_name": self.calendar_name,
            "backend_name": self.backend_name,
        }
