"""Factory for selecting the appropriate spot price adapter."""

from __future__ import annotations

import logging

from .ispotprice import ISpotPrice
from .nordpool import NordPoolAdapter

_LOGGER = logging.getLogger(__name__)


class SpotPriceFactory:
    """Creates the correct spot price adapter based on configured entity."""

    @staticmethod
    def create(
        hass, entity_id: str, test: bool = False
    ) -> ISpotPrice:
        # For now, only NordPool is supported.
        # Entity ID detection could be extended for EnergiDataService etc.
        return NordPoolAdapter(hass, entity_id, test)
