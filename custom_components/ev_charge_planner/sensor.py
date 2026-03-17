"""Sensor platform for EV Charge Planner."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_VEHICLE_NAME, CONF_VEHICLES, DOMAIN, HUB
from .service.optimizer import round_kr

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    hub = hass.data[DOMAIN][f"{HUB}_{config_entry.entry_id}"]
    vehicles = config_entry.data.get(CONF_VEHICLES, [])

    entities = [
        ChargePlannerSensor(hub, vc[CONF_VEHICLE_NAME], config_entry.entry_id) for vc in vehicles
    ]
    async_add_entities(entities)


class ChargePlannerSensor(SensorEntity):
    """Sensor showing optimal charge start time for a vehicle."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_should_poll = False

    def __init__(self, hub, vehicle_name: str, entry_id: str) -> None:
        self._hub = hub
        self._vehicle_name = vehicle_name
        self._attr_name = f"{vehicle_name} charge period"
        self._attr_unique_id = f"ev_charge_planner_{entry_id}_{vehicle_name}"
        self._periods_list_md: str = ""
        self._all_sequences: dict[str, str] = {}

    async def async_added_to_hass(self) -> None:
        """Register callback with hub when entity is added."""
        # Load initial data before registering callback to avoid
        # async_write_ha_state() before entity is fully registered.
        await self._hub.async_update()
        self._update_from_hub()
        self._hub.register_update_callback(self._on_hub_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed."""
        self._hub.unregister_update_callback(self._on_hub_update)

    @callback
    def _on_hub_update(self) -> None:
        """Handle hub update notification."""
        self._update_from_hub()
        self.async_write_ha_state()

    def _update_from_hub(self) -> None:
        """Read latest results from hub."""
        result = self._hub.get_result(self._vehicle_name)

        if result is None or not result.needs_charging or result.best_period is None:
            self._attr_native_value = None
            self._periods_list_md = ""
            self._all_sequences = {}
            return

        self._attr_native_value = result.best_period.start
        self._periods_list_md = self._format_periods(result)
        self._all_sequences = self._make_sequences(result)

    @property
    def extra_state_attributes(self) -> dict:
        result = self._hub.get_result(self._vehicle_name)
        attrs: dict = {
            "periods_list_md": self._periods_list_md,
            "All sequences": self._all_sequences,
        }
        if result is not None:
            attrs["current_soc"] = result.current_soc
            attrs["target_soc"] = result.target_soc
            attrs["charge_power_kw"] = result.charge_power_kw
            attrs["charging_enabled"] = result.enabled
            attrs["deadline"] = (
                result.deadline.strftime("%H:%M") if result.deadline is not None else None
            )
        return attrs

    @property
    def _currency_unit(self) -> str:
        """Short display unit from currency code."""
        code = self._hub.currency.upper()
        if code in ("SEK", "NOK", "DKK"):
            return "kr"
        if code == "EUR":
            return "\u20ac"
        return code

    @property
    def _cost_decimals(self) -> int:
        """Decimal places for displaying costs (matches rounding precision)."""
        return 1 if self._hub.currency.upper() in ("SEK", "NOK", "DKK") else 2

    def _make_sequences(self, result) -> dict[str, str]:
        """Build All sequences dict matching peaqnext format."""
        if not result.all_periods:
            return {}

        unit = self._currency_unit
        now = self._hub.dt_model.now()
        sequences: dict[str, str] = {}
        for p in result.all_periods:
            t1 = p.start.strftime("%H:%M")
            if p.start.date() > now.date():
                t1 += "\u207a\u00b9"
            t2 = p.end.strftime("%H:%M")
            if p.end.date() > now.date():
                t2 += "\u207a\u00b9"
            prefix = ">> " if p.start.hour == now.hour and p.start.date() == now.date() else ""
            sequences[f"{prefix}{t1}-{t2}"] = f"{round_kr(p.total_cost, self._hub.currency):.{self._cost_decimals}f} {unit}"
        return sequences

    def _format_periods(self, result) -> str:
        """Format all periods as markdown table."""
        if not result.all_periods:
            return ""

        unit = self._currency_unit
        now = self._hub.dt_model.now()
        lines = ["| Period | Kostnad |", "|---|---|"]
        for p in result.all_periods:
            t1 = p.start.strftime("%H:%M")
            if p.start.date() > now.date():
                t1 += "\u207a\u00b9"  # ⁺¹
            t2 = p.end.strftime("%H:%M")
            if p.end.date() > now.date():
                t2 += "\u207a\u00b9"  # ⁺¹
            lines.append(f"| {t1}\u2013{t2} | {round_kr(p.total_cost, self._hub.currency):.{self._cost_decimals}f} {unit} |")
        return "\n".join(lines)
