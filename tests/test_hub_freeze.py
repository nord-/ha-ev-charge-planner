"""Tests for Hub freeze-state persistence and price caching."""

import time
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.ev_charge_planner.const import (
    CONF_BATTERY_CAPACITY,
    CONF_CHARGE_POWER,
    CONF_DEADLINE_ENTITY,
    CONF_ENABLED_ENTITY,
    CONF_FEES_ENTITY,
    CONF_FEES_FIXED,
    CONF_PRICE_SENSOR,
    CONF_SOC_SENSOR,
    CONF_SOC_TARGET_FIXED,
    CONF_VAT_PERCENT,
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

    @property
    def currency(self):
        return "SEK"

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
    # Second update — should use cached prices
    results2 = await hub.async_update()
    assert results2["Tesla"].best_period is not None


class FakeStateReader:
    """Stub StateReader for testing."""

    def __init__(self, states: dict[str, str]):
        self._states = states

    def get_state(self, entity_id: str) -> str | None:
        return self._states.get(entity_id)


@pytest.mark.asyncio
async def test_deadline_rolls_to_tomorrow_when_passed():
    """If deadline time (e.g. 07:00) has already passed, it should be tomorrow."""
    hub = Hub(None, [make_vehicle_config()], test=True)
    # 22:00 — deadline 07:00 already passed today
    now = datetime(2024, 1, 15, 22, 0)
    reader = FakeStateReader({"input_datetime.deadline": "07:00:00"})
    hub._state_reader = reader

    config = make_vehicle_config()
    config[CONF_DEADLINE_ENTITY] = "input_datetime.deadline"
    hub._vehicle_configs = [config]

    deadline = hub._get_deadline("input_datetime.deadline", now)
    assert deadline.day == 16, "Deadline should roll to next day"
    assert deadline.hour == 7
    assert deadline.minute == 0


@pytest.mark.asyncio
async def test_deadline_works_with_aware_now():
    """Deadline must be tz-aware when now is tz-aware (UTC from DTModel)."""
    hub = Hub(None, [make_vehicle_config()], test=True)
    now = datetime(2024, 1, 15, 22, 0, tzinfo=UTC)
    reader = FakeStateReader({"input_datetime.deadline": "07:00:00"})
    hub._state_reader = reader

    deadline = hub._get_deadline("input_datetime.deadline", now)
    assert deadline.tzinfo is not None, "Deadline must be tz-aware when now is tz-aware"
    assert deadline.day == 16


@pytest.mark.asyncio
async def test_vat_percent_to_multiplier():
    """VAT percent is converted to multiplier in Vehicle."""
    config = make_vehicle_config()
    config[CONF_VAT_PERCENT] = 25
    hub = Hub(None, [config], test=True)
    hub.dt_model.set_now(datetime(2024, 1, 1, 0, 0))
    vehicles = hub._build_vehicles(hub.dt_model.now())
    assert vehicles[0].vat_multiplier == 1.25


@pytest.mark.asyncio
async def test_vat_percent_decimal():
    """Decimal VAT percent (e.g. 12.5%)."""
    config = make_vehicle_config()
    config[CONF_VAT_PERCENT] = 12.5
    hub = Hub(None, [config], test=True)
    hub.dt_model.set_now(datetime(2024, 1, 1, 0, 0))
    vehicles = hub._build_vehicles(hub.dt_model.now())
    assert vehicles[0].vat_multiplier == 1.125


@pytest.mark.asyncio
async def test_vat_percent_zero():
    """Zero VAT."""
    config = make_vehicle_config()
    config[CONF_VAT_PERCENT] = 0
    hub = Hub(None, [config], test=True)
    hub.dt_model.set_now(datetime(2024, 1, 1, 0, 0))
    vehicles = hub._build_vehicles(hub.dt_model.now())
    assert vehicles[0].vat_multiplier == 1.0


@pytest.mark.asyncio
async def test_fees_from_entity():
    """Fees read from entity sensor."""
    config = make_vehicle_config()
    config[CONF_FEES_ENTITY] = "sensor.fees"
    reader = FakeStateReader({"sensor.fees": "0.58"})
    hub = Hub(None, [config], test=True)
    hub._state_reader = reader
    hub.dt_model.set_now(datetime(2024, 1, 1, 0, 0))
    vehicles = hub._build_vehicles(hub.dt_model.now())
    assert vehicles[0].fees_inc_vat == 0.58


@pytest.mark.asyncio
async def test_fees_from_fixed():
    """Fees from fixed config value."""
    config = make_vehicle_config()
    config[CONF_FEES_FIXED] = 0.42
    hub = Hub(None, [config], test=True)
    hub.dt_model.set_now(datetime(2024, 1, 1, 0, 0))
    vehicles = hub._build_vehicles(hub.dt_model.now())
    assert vehicles[0].fees_inc_vat == 0.42


@pytest.mark.asyncio
async def test_fees_entity_unavailable_falls_back():
    """When fees entity is unavailable, use default."""
    config = make_vehicle_config()
    config[CONF_FEES_ENTITY] = "sensor.fees"
    reader = FakeStateReader({"sensor.fees": "unavailable"})
    hub = Hub(None, [config], test=True)
    hub._state_reader = reader
    hub.dt_model.set_now(datetime(2024, 1, 1, 0, 0))
    vehicles = hub._build_vehicles(hub.dt_model.now())
    assert vehicles[0].fees_inc_vat == 0.0


@pytest.mark.asyncio
async def test_enabled_entity_off_skips_charging():
    """Vehicle with enabled_entity=off should not need charging."""
    config = make_vehicle_config()
    config[CONF_ENABLED_ENTITY] = "input_boolean.charge_tesla"
    reader = FakeStateReader({"input_boolean.charge_tesla": "off"})
    hub = Hub(None, [config], test=True)
    hub._state_reader = reader
    hub.dt_model.set_now(datetime(2024, 1, 1, 0, 0))
    vehicles = hub._build_vehicles(hub.dt_model.now())
    assert not vehicles[0].enabled
    assert not vehicles[0].needs_charging


@pytest.mark.asyncio
async def test_enabled_entity_on_allows_charging():
    """Vehicle with enabled_entity=on should charge normally."""
    config = make_vehicle_config()
    config[CONF_ENABLED_ENTITY] = "input_boolean.charge_tesla"
    reader = FakeStateReader({"input_boolean.charge_tesla": "on"})
    hub = Hub(None, [config], test=True)
    hub._state_reader = reader
    hub.dt_model.set_now(datetime(2024, 1, 1, 0, 0))
    vehicles = hub._build_vehicles(hub.dt_model.now())
    assert vehicles[0].enabled
    assert vehicles[0].needs_charging


@pytest.mark.asyncio
async def test_enabled_entity_missing_defaults_to_true():
    """No enabled_entity configured should default to enabled."""
    config = make_vehicle_config()
    hub = Hub(None, [config], test=True)
    hub.dt_model.set_now(datetime(2024, 1, 1, 0, 0))
    vehicles = hub._build_vehicles(hub.dt_model.now())
    assert vehicles[0].enabled


@pytest.mark.asyncio
async def test_no_prices_returns_empty_results():
    """Hub returns empty results when no prices have ever been fetched."""
    stub = StubSpotPrice(None)
    config = make_vehicle_config()
    hub = Hub(None, [config], test=True, spotprice=stub)

    results = await hub.async_update()
    assert results == {}


@pytest.mark.asyncio
async def test_startup_delay_skips_optimization():
    """During startup delay, optimization is skipped even with prices available."""
    now = datetime(2024, 1, 1, 0, 0)
    prices = [PriceSlot(start=now + timedelta(hours=i), value=0.5) for i in range(24)]
    stub = StubSpotPrice(prices)

    config = make_vehicle_config(soc_target=60, battery=60, power=11)
    hub = Hub(None, [config], test=False, spotprice=stub)
    hub.dt_model.set_now(now)

    # Simulate async_setup() setting the startup time
    hub._setup_time = time.monotonic()

    # Update during startup delay — should return empty results
    results = await hub.async_update()
    assert results == {}

    # After startup delay expires, optimization should run
    hub._setup_time = time.monotonic() - 31
    results = await hub.async_update()
    assert results["Tesla"].best_period is not None
