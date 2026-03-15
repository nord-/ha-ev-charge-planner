"""Vehicle configuration and state."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class Vehicle:
    """Represents one EV with its charging parameters."""

    name: str
    battery_capacity_kwh: float
    charge_power_kw: float
    current_soc: float  # 0-100
    target_soc: float  # 0-100
    deadline: datetime
    fees_inc_vat: float = 0.0
    vat_multiplier: float = 1.25

    # Frozen state: when charging is active, ignore parameter changes
    frozen: bool = False
    frozen_duration: float | None = None

    @property
    def duration_hours(self) -> float:
        """Charging duration rounded up to nearest quarter hour."""
        if self.frozen and self.frozen_duration is not None:
            return self.frozen_duration
        return self._calc_duration()

    @property
    def needs_charging(self) -> bool:
        return self.duration_hours > 0

    def _calc_duration(self) -> float:
        if self.target_soc <= self.current_soc or self.charge_power_kw <= 0:
            return 0.0
        energy_kwh = (self.target_soc - self.current_soc) / 100 * self.battery_capacity_kwh
        hours = energy_kwh / self.charge_power_kw
        return math.ceil(hours * 4) / 4

    def freeze(self) -> None:
        """Freeze current duration — charging has started."""
        self.frozen_duration = self._calc_duration()
        self.frozen = True

    def unfreeze(self) -> None:
        """Unfreeze — charging period has ended."""
        self.frozen = False
        self.frozen_duration = None
