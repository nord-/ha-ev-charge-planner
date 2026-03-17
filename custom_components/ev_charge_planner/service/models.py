"""Data models for charge planning results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PriceSlot:
    """One hour of electricity pricing."""

    start: datetime
    value: float  # price in currency/kWh before fees/VAT


@dataclass
class ChargePeriod:
    """A candidate charging window for a vehicle."""

    start: datetime
    end: datetime
    avg_price: float  # average price incl fees and VAT (per kWh)
    total_cost: float  # total cost in currency
    duration_hours: float  # charging duration needed
    hours_used: int  # number of price slots consumed

    def __repr__(self) -> str:
        return f"ChargePeriod({self.start:%H:%M}–{self.end:%H:%M}, cost={self.total_cost:.0f} kr)"


@dataclass
class VehicleResult:
    """Optimization result for one vehicle."""

    vehicle_name: str
    best_period: ChargePeriod | None
    all_periods: list[ChargePeriod] = field(default_factory=list)
    duration_hours: float = 0.0
    needs_charging: bool = False
    current_soc: float | None = None
    target_soc: float | None = None
    charge_power_kw: float | None = None
    enabled: bool = True
    deadline: datetime | None = None
