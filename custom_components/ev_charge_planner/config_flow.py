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
    CONF_FEES_ENTITY,
    CONF_FEES_FIXED,
    CONF_PRICE_SENSOR,
    CONF_SOC_SENSOR,
    CONF_SOC_TARGET_ENTITY,
    CONF_SOC_TARGET_FIXED,
    CONF_VAT_PERCENT,
    CONF_VEHICLE_NAME,
    CONF_VEHICLES,
    DEFAULT_FEES,
    DEFAULT_SOC_TARGET,
    DEFAULT_VAT_PERCENT,
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
        vol.Optional(CONF_FEES_ENTITY): str,
        vol.Optional(CONF_FEES_FIXED, default=DEFAULT_FEES): vol.Coerce(float),
        vol.Optional(CONF_VAT_PERCENT, default=DEFAULT_VAT_PERCENT): vol.All(
            vol.Coerce(float), vol.Range(min=0)
        ),
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

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EVChargePlannerOptionsFlow:
        return EVChargePlannerOptionsFlow(config_entry)


class EVChargePlannerOptionsFlow(config_entries.OptionsFlow):
    """Handle options for EV Charge Planner."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show list of vehicles to edit."""
        vehicles = self._config_entry.data.get(CONF_VEHICLES, [])

        if len(vehicles) == 1:
            self._vehicle_index = 0
            return await self.async_step_edit_vehicle(user_input)

        if user_input is not None:
            self._vehicle_index = int(user_input["vehicle_index"])
            return await self.async_step_edit_vehicle()

        vehicle_names = {str(i): vc[CONF_VEHICLE_NAME] for i, vc in enumerate(vehicles)}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required("vehicle_index"): vol.In(vehicle_names)}),
        )

    async def async_step_edit_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit a vehicle's configuration."""
        vehicles = list(self._config_entry.data.get(CONF_VEHICLES, []))
        current = vehicles[self._vehicle_index]

        if user_input is not None:
            vehicles[self._vehicle_index] = {**current, **user_input}
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data={**self._config_entry.data, CONF_VEHICLES: vehicles},
            )
            return self.async_create_entry(data={})

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SOC_TARGET_FIXED,
                    default=current.get(CONF_SOC_TARGET_FIXED, DEFAULT_SOC_TARGET),
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_SOC_TARGET_ENTITY,
                    description={"suggested_value": current.get(CONF_SOC_TARGET_ENTITY, "")},
                ): str,
                vol.Optional(
                    CONF_CHARGE_POWER,
                    description={"suggested_value": current.get(CONF_CHARGE_POWER)},
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_CHARGE_POWER_ENTITY,
                    description={"suggested_value": current.get(CONF_CHARGE_POWER_ENTITY, "")},
                ): str,
                vol.Optional(
                    CONF_FEES_ENTITY,
                    description={"suggested_value": current.get(CONF_FEES_ENTITY, "")},
                ): str,
                vol.Required(
                    CONF_FEES_FIXED,
                    default=current.get(CONF_FEES_FIXED, DEFAULT_FEES),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_VAT_PERCENT,
                    default=current.get(CONF_VAT_PERCENT, DEFAULT_VAT_PERCENT),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
            }
        )

        return self.async_show_form(
            step_id="edit_vehicle",
            data_schema=schema,
            description_placeholders={"vehicle_name": current[CONF_VEHICLE_NAME]},
        )
