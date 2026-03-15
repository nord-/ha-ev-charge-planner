"""Central coordinator for EV charge planning."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from ..const import (
    CONF_BATTERY_CAPACITY,
    CONF_CHARGE_POWER,
    CONF_CHARGE_POWER_ENTITY,
    CONF_DEADLINE_ENTITY,
    CONF_GRID_FEES_EX_VAT,
    CONF_PRICE_SENSOR,
    CONF_SOC_SENSOR,
    CONF_SOC_TARGET,
    CONF_SOC_TARGET_ENTITY,
    CONF_SOC_TARGET_FIXED,
    CONF_VEHICLE_NAME,
    DEFAULT_GRID_FEES,
    DEFAULT_SOC_TARGET,
    DEFAULT_VAT_MULTIPLIER,
    SPOTPRICE_THROTTLE_SECONDS,
)
from .dt_model import DTModel
from .models import VehicleResult
from .optimizer import optimize_joint
from .spotprice.nordpool import NordPoolAdapter
from .vehicle import Vehicle

_LOGGER = logging.getLogger(__name__)


class Hub:
    """Manages vehicles, listens to state changes, runs optimization."""

    def __init__(
        self, hass: HomeAssistant | None, vehicle_configs: list[dict], test: bool = False
    ):
        self._hass = hass
        self._vehicle_configs = vehicle_configs
        self._test = test
        self.dt_model = DTModel()
        self._results: dict[str, VehicleResult] = {}
        self._last_update: float = 0
        self._unsub_listeners: list = []
        self._update_callbacks: list = []

        # Freeze state persisted across update cycles:
        # {vehicle_name: (frozen_duration, original_period_end)}
        self._freeze_state: dict[str, tuple[float, datetime]] = {}

        self._prices: list = []

        # Determine price sensor (all vehicles share the same one)
        price_entity = vehicle_configs[0].get(CONF_PRICE_SENSOR) if vehicle_configs else None
        self.spotprice = NordPoolAdapter(hass, price_entity, test)

    async def async_setup(self) -> None:
        """Set up state listeners."""
        if self._test or not self._hass:
            return

        # Listen to price sensor changes
        entities_to_track = set()
        if self.spotprice.entity:
            entities_to_track.add(self.spotprice.entity)

        # Listen to all vehicle-related entities
        for vc in self._vehicle_configs:
            for key in (
                CONF_SOC_SENSOR,
                CONF_SOC_TARGET_ENTITY,
                CONF_CHARGE_POWER_ENTITY,
                CONF_DEADLINE_ENTITY,
            ):
                entity = vc.get(key)
                if entity:
                    entities_to_track.add(entity)

        if entities_to_track:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self._hass, list(entities_to_track), self._async_on_change
                )
            )

    @callback
    def _async_on_change(self, event: Event) -> None:
        """Handle state change of a tracked entity."""
        self._hass.async_create_task(self.async_update())

    async def async_update(self) -> dict[str, VehicleResult]:
        """Run optimization (throttled, but always allow first successful run)."""
        now_mono = time.monotonic()
        if self._results and now_mono - self._last_update < SPOTPRICE_THROTTLE_SECONDS:
            return self._results

        # Update spot prices
        prices = await self.spotprice.async_fetch()
        if prices is not None:
            self._prices = prices
        if not self._prices:
            _LOGGER.debug("Spot prices not yet available")
            return self._results

        now = self.dt_model.now()

        # Build Vehicle objects from current HA state
        vehicles = self._build_vehicles(now)

        # Run joint optimization
        self._results = optimize_joint(vehicles, self._prices, now)
        self._last_update = now_mono

        # Manage freeze state
        self._manage_freeze(vehicles, now)

        # Notify listeners
        for cb in self._update_callbacks:
            cb()

        return self._results

    def _build_vehicles(self, now: datetime) -> list[Vehicle]:
        """Build Vehicle objects from config + current HA state.

        Applies persisted freeze state so that frozen vehicles retain their
        locked duration across update cycles.
        """
        vehicles = []
        for vc in self._vehicle_configs:
            name = vc[CONF_VEHICLE_NAME]
            current_soc = self._get_state_float(vc.get(CONF_SOC_SENSOR), 0.0)

            # Target SoC: entity or fixed value
            target_entity = vc.get(CONF_SOC_TARGET_ENTITY)
            if target_entity:
                target_soc = self._get_state_float(target_entity, DEFAULT_SOC_TARGET)
            else:
                target_soc = float(vc.get(CONF_SOC_TARGET_FIXED, DEFAULT_SOC_TARGET))

            # Charge power: entity or fixed value
            power_entity = vc.get(CONF_CHARGE_POWER_ENTITY)
            if power_entity:
                charge_power = self._get_state_float(power_entity, 0.0)
            else:
                charge_power = float(vc.get(CONF_CHARGE_POWER, 0.0))

            # Deadline from input_datetime entity
            deadline = self._get_deadline(vc.get(CONF_DEADLINE_ENTITY), now)

            v = Vehicle(
                name=name,
                battery_capacity_kwh=float(vc[CONF_BATTERY_CAPACITY]),
                charge_power_kw=charge_power,
                current_soc=current_soc,
                target_soc=target_soc,
                deadline=deadline,
                grid_fees_ex_vat=float(vc.get(CONF_GRID_FEES_EX_VAT, DEFAULT_GRID_FEES)),
                vat_multiplier=DEFAULT_VAT_MULTIPLIER,
            )

            # Restore persisted freeze state (only if not expired)
            if name in self._freeze_state:
                _, original_end = self._freeze_state[name]
                if now < original_end:
                    v.frozen = True
                    v.frozen_duration = self._freeze_state[name][0]
                else:
                    del self._freeze_state[name]

            vehicles.append(v)
        return vehicles

    def _manage_freeze(self, vehicles: list[Vehicle], now: datetime) -> None:
        """Freeze/unfreeze vehicles, persisting state in Hub across cycles.

        Uses the *original* period end time (captured at freeze) for unfreeze
        decisions, so recomputed periods don't cause premature or delayed unfreeze.
        """
        for v in vehicles:
            result = self._results.get(v.name)
            if v.name in self._freeze_state:
                # Already frozen — check against original period end
                _, original_end = self._freeze_state[v.name]
                if now >= original_end:
                    v.unfreeze()
                    del self._freeze_state[v.name]
                    _LOGGER.info("Vehicle %s charging ended, unfreezing", v.name)
            elif result and result.best_period:
                if now >= result.best_period.start and now < result.best_period.end:
                    v.freeze()
                    self._freeze_state[v.name] = (
                        v.frozen_duration,
                        result.best_period.end,
                    )
                    _LOGGER.info("Vehicle %s charging started, freezing", v.name)

    def _get_state_float(self, entity_id: str | None, default: float) -> float:
        if not entity_id or not self._hass:
            return default
        state = self._hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return default
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return default

    def _get_deadline(self, entity_id: str | None, now: datetime) -> datetime:
        """Parse deadline from input_datetime entity."""
        if not entity_id or not self._hass:
            return now + timedelta(hours=8)  # fallback
        state = self._hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return now + timedelta(hours=8)
        # input_datetime state is "HH:MM:SS" or "YYYY-MM-DD HH:MM:SS"
        try:
            time_str = state.state
            if len(time_str) <= 8:  # "HH:MM" or "HH:MM:SS"
                parts = time_str.split(":")
                hour, minute = int(parts[0]), int(parts[1])
                return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                from datetime import datetime as dt

                return dt.fromisoformat(time_str)
        except (ValueError, IndexError):
            return now + timedelta(hours=8)

    def get_result(self, vehicle_name: str) -> VehicleResult | None:
        return self._results.get(vehicle_name)

    def register_update_callback(self, callback) -> None:
        self._update_callbacks.append(callback)

    def unregister_update_callback(self, callback) -> None:
        try:
            self._update_callbacks.remove(callback)
        except ValueError:
            pass

    async def async_teardown(self) -> None:
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
