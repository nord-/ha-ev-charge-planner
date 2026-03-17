"""Abstract base for spot price sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import PriceSlot


class ISpotPrice(ABC):
    """Interface for fetching spot prices.

    Implementations may hold state (e.g. last-known currency) but price
    storage is the caller's (Hub's) responsibility.
    """

    @property
    @abstractmethod
    def entity(self) -> str | None:
        """Entity ID being tracked (for state-change listeners)."""

    @property
    @abstractmethod
    def currency(self) -> str:
        """Currency code from the spot price source (e.g. 'SEK', 'EUR')."""

    @abstractmethod
    async def async_fetch(self) -> list[PriceSlot] | None:
        """Fetch current prices. Returns None if unavailable."""
