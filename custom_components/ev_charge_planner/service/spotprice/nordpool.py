"""NordPool spot price adapter."""

from __future__ import annotations

import logging

from ..models import PriceSlot
from .dto import NordPoolDTO
from .ispotprice import ISpotPrice

_LOGGER = logging.getLogger(__name__)


class NordPoolAdapter(ISpotPrice):
    """Fetches prices from the NordPool HA integration."""

    def __init__(self, hass, entity_id: str | None = None, test: bool = False):
        self._hass = hass
        self._entity_id = entity_id
        self._test = test

    @property
    def entity(self) -> str | None:
        return self._entity_id

    async def async_fetch(self) -> list[PriceSlot] | None:
        if self._test or not self._hass or not self._entity_id:
            return None

        state = self._hass.states.get(self._entity_id)
        if state is None:
            _LOGGER.warning("NordPool entity %s not found", self._entity_id)
            return None

        dto = NordPoolDTO()
        dto.set_from_state(state)
        prices = dto.all_prices
        return prices if prices else None
