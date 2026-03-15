"""Config flow for EV Charge Planner."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries

from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_CHARGE_POWER,
    CONF_CHARGE_POWER_ENTITY,
    CONF_DEADLINE_ENTITY,
    CONF_GRID_FEES_EX_VAT,
    CONF_PRICE_SENSOR,
    CONF_SOC_SENSOR,
    CONF_SOC_TARGET_ENTITY,
    CONF_SOC_TARGET_FIXED,
    CONF_VEHICLE_NAME,
    CONF_VEHICLES,
    DEFAULT_GRID_FEES,
    DEFAULT_SOC_TARGET,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

VEHICLE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_VEHICLE_NAME): str,
        vol.Required(CONF_SOC_SENSOR): str,
        vol.Optional(CONF_SOC_TARGET_ENTITY): str,
        vol.Optional(CONF_SOC_TARGET_FIXED, default=DEFAULT_SOC_TARGET): vol.Coerce(float),
        vol.Required(CONF_BATTERY_CAPACITY): vol.Coerce(float),
        vol.Optional(CONF_CHARGE_POWER): vol.Coerce(float),
        vol.Optional(CONF_CHARGE_POWER_ENTITY): str,
        vol.Required(CONF_DEADLINE_ENTITY): str,
        vol.Required(CONF_PRICE_SENSOR): str,
        vol.Optional(CONF_GRID_FEES_EX_VAT, default=DEFAULT_GRID_FEES): vol.Coerce(float),
    }
)


class EVChargePlannerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EV Charge Planner."""

    VERSION = 1

    def __init__(self) -> None:
        self._vehicles: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """First vehicle configuration."""
        return await self._async_vehicle_step(user_input, "user")

    async def async_step_add_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add another vehicle."""
        return await self._async_vehicle_step(user_input, "add_vehicle")

    async def _async_vehicle_step(
        self, user_input: dict[str, Any] | None, step_id: str
    ) -> config_entries.ConfigFlowResult:
        errors = {}

        if user_input is not None:
            self._vehicles.append(user_input)
            return await self.async_step_finish()

        return self.async_show_form(
            step_id=step_id,
            data_schema=VEHICLE_SCHEMA,
            errors=errors,
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose to add more vehicles or finish."""
        if user_input is not None:
            if user_input.get("add_another"):
                return await self.async_step_add_vehicle()

            return self.async_create_entry(
                title="EV Charge Planner",
                data={CONF_VEHICLES: self._vehicles},
            )

        return self.async_show_form(
            step_id="finish",
            data_schema=vol.Schema({vol.Optional("add_another", default=False): bool}),
        )
