"""Abstract base for spot price sources."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..models import PriceSlot
from .dto import SpotPriceDTO

_LOGGER = logging.getLogger(__name__)


class ISpotPrice(ABC):
    """Interface for spot price integrations."""

    def __init__(self, hass, entity_id: str | None = None, test: bool = False):
        self._hass = hass
        self._entity_id = entity_id
        self._prices: list[PriceSlot] = []
        self._is_initialized = False
        self._test = test

    @property
    def entity(self) -> str | None:
        return self._entity_id

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    @property
    def prices(self) -> list[PriceSlot]:
        return self._prices

    @abstractmethod
    async def async_update(self) -> SpotPriceDTO | None:
        """Fetch current prices and return DTO."""

    async def async_set_dto(self, dto: SpotPriceDTO) -> None:
        """Set prices from a DTO (used by adapter and tests)."""
        self._prices = dto.all_prices
        self._is_initialized = bool(self._prices)
