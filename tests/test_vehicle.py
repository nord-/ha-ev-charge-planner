"""Tests for Vehicle model."""

from datetime import datetime

from custom_components.ev_charge_planner.service.vehicle import Vehicle


def test_duration_matches_template_formula():
    """Verify duration matches the Jinja2 template: ceil(energy/power * 4) / 4."""
    # Tesla Model Y: 75 kWh battery, 11 kW charger, 50->80% SoC
    v = Vehicle(
        name="Tesla",
        battery_capacity_kwh=75,
        charge_power_kw=11,
        current_soc=50,
        target_soc=80,
        deadline=datetime(2024, 1, 1, 7, 0),
    )
    # energy = 0.3 * 75 = 22.5 kWh
    # hours = 22.5 / 11 = 2.045...
    # ceil(2.045 * 4) / 4 = ceil(8.18) / 4 = 9/4 = 2.25
    assert v.duration_hours == 2.25


def test_duration_byd_dolphin():
    """BYD Dolphin: 44.9 kWh battery, 7 kW charger."""
    v = Vehicle(
        name="Dolphin",
        battery_capacity_kwh=44.9,
        charge_power_kw=7,
        current_soc=30,
        target_soc=80,
        deadline=datetime(2024, 1, 1, 7, 0),
    )
    # energy = 0.5 * 44.9 = 22.45 kWh
    # hours = 22.45 / 7 = 3.207...
    # ceil(3.207 * 4) / 4 = ceil(12.828) / 4 = 13/4 = 3.25
    assert v.duration_hours == 3.25
