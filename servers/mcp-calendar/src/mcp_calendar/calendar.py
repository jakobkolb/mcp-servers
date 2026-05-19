from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


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


@dataclass
class CalendarBackend(ABC):
    name: str = field(default="", init=False)

    @abstractmethod
    def list_calendars(self) -> list[str]: ...

    @abstractmethod
    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...

    @abstractmethod
    def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        calendar_name: str | None = None,
        description: str | None = None,
        location: str | None = None,
        alarms: list[timedelta] | None = None,
    ) -> CalendarEvent: ...

    @abstractmethod
    def update_event(
        self,
        uid: str,
        summary: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
        alarms: list[timedelta] | None = None,
    ) -> CalendarEvent: ...

    @abstractmethod
    def delete_event(self, uid: str) -> None: ...

    @abstractmethod
    def get_freebusy(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]: ...

    @abstractmethod
    def create_task(
        self,
        summary: str,
        calendar_name: str | None = None,
        description: str | None = None,
        due: date | datetime | None = None,
        priority: int = 0,
    ) -> CalendarTask: ...

    @abstractmethod
    def update_task(
        self,
        uid: str,
        summary: str | None = None,
        description: str | None = None,
        due: date | datetime | None = None,
        priority: int | None = None,
        status: str | None = None,
    ) -> CalendarTask: ...

    @abstractmethod
    def delete_task(self, uid: str) -> None: ...

    @abstractmethod
    def list_tasks(self, calendar_name: str | None = None) -> list[CalendarTask]: ...
