from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime


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
    ) -> CalendarEvent: ...

    @abstractmethod
    def delete_event(self, uid: str) -> None: ...

    @abstractmethod
    def get_freebusy(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]: ...
