"""Tests for the charge optimizer — core algorithm."""

import math
from datetime import datetime, timedelta

import pytest

from custom_components.ev_charge_planner.service.models import ChargePeriod, PriceSlot
from custom_components.ev_charge_planner.service.optimizer import (
    calculate_cutoff,
    calculate_deadline,
    find_periods_single,
    optimize_joint,
)
from custom_components.ev_charge_planner.service.vehicle import Vehicle


# --- Helpers ---

def make_prices(start: datetime, values: list[float]) -> list[PriceSlot]:
    """Create hourly price slots from a list of values."""
    return [
        PriceSlot(start=start + timedelta(hours=i), value=v)
        for i, v in enumerate(values)
    ]


def make_vehicle(
    name: str,
    current_soc: float,
    target_soc: float,
    battery_kwh: float = 60.0,
    charge_power_kw: float = 11.0,
    deadline: datetime | None = None,
    fees: float = 0.0,
) -> Vehicle:
    return Vehicle(
        name=name,
        battery_capacity_kwh=battery_kwh,
        charge_power_kw=charge_power_kw,
        current_soc=current_soc,
        target_soc=target_soc,
        deadline=deadline or datetime(2024, 1, 1, 7, 0),
        grid_fees_ex_vat=fees,
    )


# --- Duration calculation ---

class TestVehicleDuration:
    def test_basic_duration(self):
        v = make_vehicle("test", 50, 80, battery_kwh=60, charge_power_kw=11)
        # (80-50)/100 * 60 / 11 = 1.636... -> ceil to 1.75
        assert v.duration_hours == 1.75

    def test_no_charging_needed(self):
        v = make_vehicle("test", 80, 80)
        assert v.duration_hours == 0.0
        assert not v.needs_charging

    def test_target_below_current(self):
        v = make_vehicle("test", 90, 80)
        assert v.duration_hours == 0.0

    def test_full_charge(self):
        v = make_vehicle("test", 0, 100, battery_kwh=60, charge_power_kw=11)
        # 60/11 = 5.454... -> ceil to 5.5
        assert v.duration_hours == 5.5

    def test_quarter_hour_rounding(self):
        v = make_vehicle("test", 0, 100, battery_kwh=44, charge_power_kw=11)
        # 44/11 = 4.0 exactly
        assert v.duration_hours == 4.0

    def test_freeze_preserves_duration(self):
        v = make_vehicle("test", 50, 80, battery_kwh=60, charge_power_kw=11)
        original = v.duration_hours
        v.freeze()
        v.current_soc = 70  # SoC changed during charging
        assert v.duration_hours == original  # frozen value

    def test_unfreeze_recalculates(self):
        v = make_vehicle("test", 50, 80, battery_kwh=60, charge_power_kw=11)
        v.freeze()
        v.current_soc = 70
        v.unfreeze()
        # (80-70)/100 * 60 / 11 = 0.545... -> 0.75
        assert v.duration_hours == 0.75


# --- Cutoff and deadline ---

class TestTimeHelpers:
    def test_cutoff(self):
        now = datetime(2024, 1, 1, 15, 30)
        cutoff = calculate_cutoff(now, 1.0)
        assert cutoff == datetime(2024, 1, 1, 14, 35)

    def test_deadline_future(self):
        now = datetime(2024, 1, 1, 15, 0)
        deadline_time = datetime(2024, 1, 1, 23, 0)
        d = calculate_deadline(now, deadline_time)
        assert d == datetime(2024, 1, 1, 23, 5)

    def test_deadline_passed_wraps(self):
        now = datetime(2024, 1, 1, 15, 0)
        deadline_time = datetime(2024, 1, 1, 7, 0)
        d = calculate_deadline(now, deadline_time)
        assert d == datetime(2024, 1, 2, 7, 5)


# --- Single vehicle optimization ---

class TestFindPeriodsSingle:
    def test_finds_cheapest_hour(self):
        start = datetime(2024, 1, 1, 0, 0)
        # 24 hours, hour 3 is cheapest
        values = [1.0] * 24
        values[3] = 0.1
        prices = make_prices(start, values)

        periods = find_periods_single(
            prices=prices,
            duration=1.0,
            deadline=datetime(2024, 1, 1, 23, 5),
            cutoff=datetime(2023, 12, 31, 23, 5),
            fees_ex_vat=0.0,
            vat_multiplier=1.25,
            charge_power_kw=11.0,
        )

        assert len(periods) > 0
        assert periods[0].start.hour == 3

    def test_no_charging_needed(self):
        prices = make_prices(datetime(2024, 1, 1), [1.0] * 24)
        periods = find_periods_single(
            prices, 0.0, datetime(2024, 1, 2), datetime(2024, 1, 1), 0.0, 1.25, 11.0
        )
        assert periods == []

    def test_respects_deadline(self):
        start = datetime(2024, 1, 1, 0, 0)
        prices = make_prices(start, [1.0] * 24)
        # Only 2 hours before deadline, need 3 hours -> limited options
        periods = find_periods_single(
            prices=prices,
            duration=3.0,
            deadline=datetime(2024, 1, 1, 5, 5),
            cutoff=datetime(2023, 12, 31, 23, 5),
            fees_ex_vat=0.0,
            vat_multiplier=1.25,
            charge_power_kw=11.0,
        )
        # All periods must end before deadline
        for p in periods:
            assert p.end <= datetime(2024, 1, 1, 5, 5)

    def test_fees_and_vat_included(self):
        start = datetime(2024, 1, 1, 0, 0)
        prices = make_prices(start, [1.0])  # 1 kr/kWh
        periods = find_periods_single(
            prices=prices,
            duration=1.0,
            deadline=datetime(2024, 1, 1, 2, 5),
            cutoff=datetime(2023, 12, 31, 23, 5),
            fees_ex_vat=0.5,
            vat_multiplier=1.25,
            charge_power_kw=10.0,
        )
        assert len(periods) == 1
        # avg_price = (1.0 + 0.5) * 1.25 = 1.875
        # total_cost = 1.875 * 1.0 * 10.0 = 18.75
        assert periods[0].total_cost == 18.75

    def test_overlap_increases_slots(self):
        start = datetime(2024, 1, 1, 0, 0)
        prices = make_prices(start, [1.0] * 10)

        # Without overlap: 2 hour charging -> 2 slots
        periods_alone = find_periods_single(
            prices, 2.0, datetime(2024, 1, 1, 10, 5),
            datetime(2023, 12, 31, 23, 5), 0.0, 1.25, 11.0,
        )

        # With overlap in hours 0-4: effective rate halved -> needs 4 slots
        other_window = (datetime(2024, 1, 1, 0, 0), datetime(2024, 1, 1, 4, 0))
        periods_overlap = find_periods_single(
            prices, 2.0, datetime(2024, 1, 1, 10, 5),
            datetime(2023, 12, 31, 23, 5), 0.0, 1.25, 11.0,
            other_windows=[other_window],
        )

        # Starting at hour 0: alone needs 2 slots, overlapping needs 4
        alone_h0 = next(p for p in periods_alone if p.start.hour == 0)
        overlap_h0 = next(p for p in periods_overlap if p.start.hour == 0)
        assert alone_h0.hours_used == 2
        assert overlap_h0.hours_used == 4


# --- Joint optimization ---

class TestOptimizeJoint:
    def test_single_vehicle(self):
        now = datetime(2024, 1, 1, 12, 0)
        prices = make_prices(datetime(2024, 1, 1, 0, 0), [1.0] * 24)
        prices[18] = PriceSlot(start=datetime(2024, 1, 1, 18, 0), value=0.1)  # cheap at 18

        v = make_vehicle("Tesla", 50, 80, deadline=datetime(2024, 1, 2, 7, 0))
        # duration = ceil((80-50)/100 * 60 / 11 * 4) / 4 = 1.75h -> 2 slots
        # Best window includes the cheap hour 18, so starts at 17 (17:00-19:00)
        results = optimize_joint([v], prices, now)

        assert "Tesla" in results
        assert results["Tesla"].needs_charging
        assert results["Tesla"].best_period is not None
        assert results["Tesla"].best_period.start.hour == 17

    def test_no_charging_needed(self):
        now = datetime(2024, 1, 1, 12, 0)
        prices = make_prices(datetime(2024, 1, 1), [1.0] * 24)
        v = make_vehicle("Tesla", 80, 80)
        results = optimize_joint([v], prices, now)
        assert not results["Tesla"].needs_charging

    def test_two_vehicles_avoid_overlap(self):
        """Two vehicles should prefer non-overlapping windows when possible.

        Two cheap 2h blocks (hours 2-3 and 10-11) separated by expensive hours.
        Overlap would force one car into expensive hours, so splitting is optimal.
        """
        now = datetime(2024, 1, 1, 0, 0)
        values = [10.0] * 24
        values[2] = 0.1
        values[3] = 0.1
        values[10] = 0.1
        values[11] = 0.1
        prices = make_prices(datetime(2024, 1, 1, 0, 0), values)

        # Each needs exactly 2h: (100-0)/100 * 22 / 11 = 2.0
        v1 = make_vehicle("Car1", 0, 100, battery_kwh=22, charge_power_kw=11,
                          deadline=datetime(2024, 1, 2, 7, 0))
        v2 = make_vehicle("Car2", 0, 100, battery_kwh=22, charge_power_kw=11,
                          deadline=datetime(2024, 1, 2, 7, 0))

        results = optimize_joint([v1, v2], prices, now)

        r1 = results["Car1"]
        r2 = results["Car2"]
        assert r1.best_period is not None
        assert r2.best_period is not None
        # Each car takes one cheap block — they must not both start at hour 2
        starts = {r1.best_period.start.hour, r2.best_period.start.hour}
        assert starts == {2, 10}

    def test_best_period_matches_combo_assignment(self):
        """best_period is derived from the winning combo via _cost_at_start.

        Two vehicles sharing a charger. Hours 2-3 are cheapest, 10-11
        slightly more expensive. The optimizer splits them across the two
        cheap blocks. Verify best_period matches the combo-assigned start
        for each vehicle (not just whatever all_periods[0] happens to be).
        """
        now = datetime(2024, 1, 1, 0, 0)
        values = [10.0] * 24
        values[2] = 0.1
        values[3] = 0.1
        values[10] = 0.15
        values[11] = 0.15
        prices = make_prices(datetime(2024, 1, 1, 0, 0), values)

        # Each needs 2h
        v1 = make_vehicle("Car1", 0, 100, battery_kwh=22, charge_power_kw=11,
                          deadline=datetime(2024, 1, 2, 7, 0))
        v2 = make_vehicle("Car2", 0, 100, battery_kwh=22, charge_power_kw=11,
                          deadline=datetime(2024, 1, 2, 7, 0))

        results = optimize_joint([v1, v2], prices, now)

        r1 = results["Car1"]
        r2 = results["Car2"]
        assert r1.best_period is not None
        assert r2.best_period is not None

        # The combo should split: one at hour 2, one at hour 10
        starts = {r1.best_period.start.hour, r2.best_period.start.hour}
        assert starts == {2, 10}

        # best_period must exist in all_periods for each vehicle
        for r in [r1, r2]:
            assert r.best_period.start in [p.start for p in r.all_periods]
            # best_period cost must match the corresponding entry in all_periods
            matching = [p for p in r.all_periods if p.start == r.best_period.start]
            assert len(matching) == 1
            assert r.best_period.total_cost == matching[0].total_cost

    def test_empty_prices(self):
        now = datetime(2024, 1, 1, 12, 0)
        v = make_vehicle("Tesla", 50, 80)
        results = optimize_joint([v], [], now)
        assert results["Tesla"].best_period is None
