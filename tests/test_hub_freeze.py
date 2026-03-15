"""Tests for Hub freeze-state persistence and price caching."""

from datetime import datetime, timedelta

import pytest

from custom_components.ev_charge_planner.const import (
    CONF_BATTERY_CAPACITY,
    CONF_CHARGE_POWER,
    CONF_DEADLINE_ENTITY,
    CONF_PRICE_SENSOR,
    CONF_SOC_SENSOR,
    CONF_SOC_TARGET_FIXED,
    CONF_VEHICLE_NAME,
)
from custom_components.ev_charge_planner.service.hub import Hub
from custom_components.ev_charge_planner.service.models import (
    ChargePeriod,
    PriceSlot,
    VehicleResult,
)
from custom_components.ev_charge_planner.service.spotprice.ispotprice import ISpotPrice


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


@pytest.mark.asyncio
async def test_freeze_persists_across_update_cycles():
    """Freeze state must survive _build_vehicles() recreating Vehicle objects."""
    hub = Hub(None, [make_vehicle_config()], test=True)
    hub.dt_model.set_now(datetime(2024, 1, 1, 3, 0))

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


class StubSpotPrice(ISpotPrice):
    """Stub ISpotPrice for testing Hub price caching."""

    def __init__(self, prices=None):
        self._prices = prices

    @property
    def entity(self):
        return None

    async def async_fetch(self):
        return self._prices


@pytest.mark.asyncio
async def test_price_caching_on_fetch_none():
    """Hub caches prices and uses them when async_fetch returns None."""
    now = datetime(2024, 1, 1, 0, 0)
    prices = [PriceSlot(start=now + timedelta(hours=i), value=0.5) for i in range(24)]
    stub = StubSpotPrice(prices)

    config = make_vehicle_config(soc_target=60, battery=60, power=11)
    hub = Hub(None, [config], test=True, spotprice=stub)
    hub.dt_model.set_now(now)

    # First update — fetches prices and produces results
    results = await hub.async_update()
    assert results["Tesla"].best_period is not None

    # Stub now returns None (e.g. temporary HA issue)
    stub._prices = None
    hub._last_update = 0  # reset throttle

    # Second update — should use cached prices
    results2 = await hub.async_update()
    assert results2["Tesla"].best_period is not None


@pytest.mark.asyncio
async def test_no_prices_returns_empty_results():
    """Hub returns empty results when no prices have ever been fetched."""
    stub = StubSpotPrice(None)
    config = make_vehicle_config()
    hub = Hub(None, [config], test=True, spotprice=stub)

    results = await hub.async_update()
    assert results == {}
