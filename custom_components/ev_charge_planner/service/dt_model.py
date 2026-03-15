"""Injectable datetime model for testability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime


@dataclass
class DTModel:
    """Provides current datetime, mockable for tests."""

    mock_dt: datetime | None = None

    def now(self) -> datetime:
        if self.mock_dt is not None:
            return self.mock_dt
        return datetime.now(tz=UTC)

    def set_now(self, dt: datetime) -> None:
        self.mock_dt = dt

    def clear(self) -> None:
        self.mock_dt = None
