from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, model_validator

from ..domain import FrozenModel


class CalendarVerification(FrozenModel):
    exchange: str
    start: date
    end: date
    sessions: tuple[date, ...]
    source: str
    verified_at: AwareDatetime

    @model_validator(mode="after")
    def bounds(self):
        if self.end < self.start or len(self.sessions) != len(set(self.sessions)):
            raise ValueError("invalid calendar coverage")
        if any(not self.start <= day <= self.end for day in self.sessions):
            raise ValueError("session outside verified coverage")
        return self


class VerifiedCalendar:
    """Official/provider sessions must be supplied; library output is only a crosscheck."""

    def __init__(self, verification: CalendarVerification) -> None:
        if not verification.source or verification.verified_at.tzinfo is None:
            raise ValueError("calendar requires dated provenance")
        self.verification = verification

    def sessions(self, start: date, end: date) -> tuple[date, ...]:
        v = self.verification
        if start < v.start or end > v.end:
            raise ValueError("calendar range not explicitly verified")
        return tuple(day for day in v.sessions if start <= day <= end)

    def complete(self, day: date, asof: datetime) -> bool:
        if day not in self.sessions(day, day):
            return False
        close = datetime.combine(day, time(15), ZoneInfo("Asia/Shanghai"))
        return asof.astimezone(UTC) >= close.astimezone(UTC)

    def compare_library(self) -> tuple[date, ...]:
        import exchange_calendars

        v = self.verification
        calendar = exchange_calendars.get_calendar("XSHG")
        candidate = {stamp.date() for stamp in calendar.sessions_in_range(v.start, v.end)}
        return tuple(sorted(candidate.symmetric_difference(v.sessions)))
