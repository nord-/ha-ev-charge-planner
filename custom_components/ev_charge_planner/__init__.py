"""EV Charge Planner — optimal charging schedules based on spot prices."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_VEHICLES, DOMAIN, HUB, PLATFORMS
from .service.hub import Hub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EV Charge Planner from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    vehicle_configs = entry.data.get(CONF_VEHICLES, [])
    hub = Hub(hass, vehicle_configs)
    hass.data[DOMAIN][f"{HUB}_{entry.entry_id}"] = hub

    await hub.async_setup()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hub_key = f"{HUB}_{entry.entry_id}"
    hub: Hub = hass.data[DOMAIN].get(hub_key)
    if hub:
        await hub.async_teardown()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(hub_key, None)

    return unload_ok
