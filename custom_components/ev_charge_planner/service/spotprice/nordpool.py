"""NordPool spot price adapter."""

from __future__ import annotations

import logging

from .dto import NordPoolDTO, SpotPriceDTO
from .ispotprice import ISpotPrice

_LOGGER = logging.getLogger(__name__)


class NordPoolAdapter(ISpotPrice):
    """Fetches prices from the NordPool HA integration."""

    async def async_update(self) -> SpotPriceDTO | None:
        if self._test or not self._hass or not self._entity_id:
            return None

        state = self._hass.states.get(self._entity_id)
        if state is None:
            _LOGGER.warning("NordPool entity %s not found", self._entity_id)
            return None

        dto = NordPoolDTO()
        dto.set_from_state(state)
        await self.async_set_dto(dto)
        return dto
