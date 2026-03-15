"""Spot price DTOs for parsing Home Assistant state objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..models import PriceSlot


@dataclass
class SpotPriceDTO:
    """Parsed spot price data from a HA integration."""

    today: list[PriceSlot] = field(default_factory=list)
    tomorrow: list[PriceSlot] = field(default_factory=list)
    tomorrow_valid: bool = False
    currency: str = ""

    @property
    def all_prices(self) -> list[PriceSlot]:
        if self.tomorrow_valid and self.tomorrow:
            return self.today + self.tomorrow
        return list(self.today)


@dataclass
class NordPoolDTO(SpotPriceDTO):
    """Parse NordPool integration state attributes.

    NordPool provides raw_today/raw_tomorrow as lists of dicts:
    [{"start": datetime, "end": datetime, "value": float}, ...]
    """

    def set_from_state(self, state) -> None:
        """Parse from a HA State object (or mock with .attributes dict)."""
        attrs = state.attributes if hasattr(state, "attributes") else state

        raw_today = attrs.get("raw_today", [])
        raw_tomorrow = attrs.get("raw_tomorrow", [])

        self.today = [
            PriceSlot(start=entry["start"], value=entry["value"])
            for entry in raw_today
            if isinstance(entry, dict) and "start" in entry and "value" in entry
        ]

        self.tomorrow = [
            PriceSlot(start=entry["start"], value=entry["value"])
            for entry in raw_tomorrow
            if isinstance(entry, dict) and "start" in entry and "value" in entry
        ]

        self.tomorrow_valid = len(self.tomorrow) > 1
        self.currency = str(attrs.get("currency", "SEK"))
