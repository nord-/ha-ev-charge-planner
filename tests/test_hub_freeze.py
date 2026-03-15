"""Tests for Hub freeze-state persistence across update cycles."""

from datetime import datetime, timedelta

import pytest

from custom_components.ev_charge_planner.service.hub import Hub
from custom_components.ev_charge_planner.service.models import PriceSlot, ChargePeriod, VehicleResult
from custom_components.ev_charge_planner.service.spotprice.dto import SpotPriceDTO
from custom_components.ev_charge_planner.const import (
    CONF_VEHICLE_NAME,
    CONF_SOC_SENSOR,
    CONF_SOC_TARGET_FIXED,
    CONF_BATTERY_CAPACITY,
    CONF_CHARGE_POWER,
    CONF_DEADLINE_ENTITY,
    CONF_PRICE_SENSOR,
)


def make_vehicle_config(name="Tesla", soc_target=80, battery=60, power=11):
    return {
        CONF_VEHICLE_NAME: name,
        CONF_SOC_SENSOR: None,
        CONF_SOC_TARGET_FIXED: soc_target,
        CONF_BATTERY_CAPACITY: battery,
        CONF_CHARGE_POWER: power,
        CONF_DEADLINE_ENTITY: None,
        CONF_PRICE_SENSOR: None,
    }


def make_prices(start, values):
    return [PriceSlot(start=start + timedelta(hours=i), value=v) for i, v in enumerate(values)]


@pytest.mark.asyncio
async def test_freeze_persists_across_update_cycles():
    """Freeze state must survive _build_vehicles() recreating Vehicle objects."""
    hub = Hub(None, [make_vehicle_config()], test=True)
    hub.dt_model.set_now(datetime(2024, 1, 1, 3, 0))

    # Set up prices and run initial optimization
    prices = make_prices(datetime(2024, 1, 1, 0, 0), [1.0] * 24)
    dto = SpotPriceDTO(today=prices, tomorrow=[], tomorrow_valid=False, currency="SEK")
    await hub.spotprice.async_set_dto(dto)

    # Build vehicles and run optimization
    vehicles = hub._build_vehicles(hub.dt_model.now())
    assert not vehicles[0].frozen

    # Simulate: optimizer found a period starting at 03:00
    hub._results = {
        "Tesla": VehicleResult(
            vehicle_name="Tesla",
            best_period=ChargePeriod(
                start=datetime(2024, 1, 1, 3, 0),
                end=datetime(2024, 1, 1, 5, 0),
                avg_price=1.25,
                total_cost=27.5,
                duration_hours=2.0,
                hours_used=2,
            ),
            all_periods=[],
            duration_hours=2.0,
            needs_charging=True,
        )
    }

    # Now is within the charging period — should freeze
    hub._manage_freeze(vehicles, datetime(2024, 1, 1, 3, 30))
    assert "Tesla" in hub._freeze_state

    # Next cycle: _build_vehicles creates new objects — freeze must be restored
    vehicles2 = hub._build_vehicles(hub.dt_model.now())
    assert vehicles2[0].frozen
    assert vehicles2[0].frozen_duration is not None


@pytest.mark.asyncio
async def test_unfreeze_after_period_ends():
    """Freeze state is cleared when charging period ends."""
    hub = Hub(None, [make_vehicle_config()], test=True)

    prices = make_prices(datetime(2024, 1, 1, 0, 0), [1.0] * 24)
    dto = SpotPriceDTO(today=prices, tomorrow=[], tomorrow_valid=False, currency="SEK")
    await hub.spotprice.async_set_dto(dto)

    vehicles = hub._build_vehicles(hub.dt_model.now())

    hub._results = {
        "Tesla": VehicleResult(
            vehicle_name="Tesla",
            best_period=ChargePeriod(
                start=datetime(2024, 1, 1, 3, 0),
                end=datetime(2024, 1, 1, 5, 0),
                avg_price=1.25,
                total_cost=27.5,
                duration_hours=2.0,
                hours_used=2,
            ),
            all_periods=[],
            duration_hours=2.0,
            needs_charging=True,
        )
    }

    # Freeze during active period
    hub._manage_freeze(vehicles, datetime(2024, 1, 1, 4, 0))
    assert "Tesla" in hub._freeze_state

    # Period has ended — should unfreeze
    hub._manage_freeze(vehicles, datetime(2024, 1, 1, 5, 30))
    assert "Tesla" not in hub._freeze_state

    # New vehicles should not be frozen
    vehicles3 = hub._build_vehicles(hub.dt_model.now())
    assert not vehicles3[0].frozen
