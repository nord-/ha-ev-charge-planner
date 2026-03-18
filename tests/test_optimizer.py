"""Tests for the charge optimizer — core algorithm."""

import math
from datetime import datetime, timedelta

import pytest

from custom_components.ev_charge_planner.service.models import ChargePeriod, PriceSlot
from custom_components.ev_charge_planner.service.optimizer import (
    calculate_cutoff,
    calculate_deadline,
    derive_entry_hours,
    find_periods_single,
    optimize_joint,
    round_kr,
)
from custom_components.ev_charge_planner.service.vehicle import Vehicle

# --- Helpers ---


def make_prices(start: datetime, values: list[float]) -> list[PriceSlot]:
    """Create hourly price slots from a list of values."""
    return [PriceSlot(start=start + timedelta(hours=i), value=v) for i, v in enumerate(values)]


def make_vehicle(
    name: str,
    current_soc: float,
    target_soc: float,
    battery_kwh: float = 60.0,
    charge_power_kw: float = 11.0,
    deadline: datetime | None = None,
    fees: float = 0.0,
    vat_multiplier: float = 1.25,
) -> Vehicle:
    return Vehicle(
        name=name,
        battery_capacity_kwh=battery_kwh,
        charge_power_kw=charge_power_kw,
        current_soc=current_soc,
        target_soc=target_soc,
        deadline=deadline or datetime(2024, 1, 1, 7, 0),
        fees_inc_vat=fees,
        vat_multiplier=vat_multiplier,
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
            fees_inc_vat=0.0,
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
            fees_inc_vat=0.0,
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
            fees_inc_vat=0.5,
            vat_multiplier=1.25,
            charge_power_kw=10.0,
        )
        assert len(periods) == 1
        # avg_price = 1.0 * 1.25 + 0.5 = 1.75
        # total_cost = 1.75 * 1.0 * 10.0 = 17.5
        assert periods[0].total_cost == 17.5

    def test_vat_25_percent_integer(self):
        """Standard Swedish VAT 25%."""
        start = datetime(2024, 1, 1, 0, 0)
        prices = make_prices(start, [2.0])
        periods = find_periods_single(
            prices=prices,
            duration=1.0,
            deadline=datetime(2024, 1, 1, 2, 5),
            cutoff=datetime(2023, 12, 31, 23, 5),
            fees_inc_vat=0.0,
            vat_multiplier=1.25,
            charge_power_kw=10.0,
        )
        # avg_price = 2.0 * 1.25 + 0.0 = 2.5
        # total_cost = 2.5 * 1.0 * 10.0 = 25.0
        assert periods[0].total_cost == 25.0

    def test_vat_12_5_percent_decimal(self):
        """Reduced VAT 12.5% (decimal)."""
        start = datetime(2024, 1, 1, 0, 0)
        prices = make_prices(start, [2.0])
        periods = find_periods_single(
            prices=prices,
            duration=1.0,
            deadline=datetime(2024, 1, 1, 2, 5),
            cutoff=datetime(2023, 12, 31, 23, 5),
            fees_inc_vat=0.0,
            vat_multiplier=1.125,
            charge_power_kw=10.0,
        )
        # avg_price = 2.0 * 1.125 = 2.25
        # total_cost = 2.25 * 1.0 * 10.0 = 22.5
        assert periods[0].total_cost == 22.5

    def test_vat_zero_percent(self):
        """Zero VAT (e.g. some jurisdictions)."""
        start = datetime(2024, 1, 1, 0, 0)
        prices = make_prices(start, [2.0])
        periods = find_periods_single(
            prices=prices,
            duration=1.0,
            deadline=datetime(2024, 1, 1, 2, 5),
            cutoff=datetime(2023, 12, 31, 23, 5),
            fees_inc_vat=0.58,
            vat_multiplier=1.0,
            charge_power_kw=10.0,
        )
        # avg_price = 2.0 * 1.0 + 0.58 = 2.58
        # total_cost = 2.58 * 1.0 * 10.0 = 25.8
        assert periods[0].total_cost == 25.8

    def test_fees_with_vat_combined(self):
        """Fees inc VAT + spot with VAT — realistic scenario."""
        start = datetime(2024, 1, 1, 0, 0)
        prices = make_prices(start, [1.0])
        periods = find_periods_single(
            prices=prices,
            duration=1.0,
            deadline=datetime(2024, 1, 1, 2, 5),
            cutoff=datetime(2023, 12, 31, 23, 5),
            fees_inc_vat=0.58,
            vat_multiplier=1.25,
            charge_power_kw=11.0,
        )
        # avg_price = 1.0 * 1.25 + 0.58 = 1.83
        # total_cost = 1.83 * 1.0 * 11.0 = 20.13
        assert periods[0].total_cost == 20.13

    def test_sort_by_rounded_cost_then_earliest_start(self):
        """Periods with same cost rounded to 1 decimal (SEK) should sort by earliest start.

        When two start times yield costs that differ by less than 0.1 kr,
        the earlier start should come first — no point delaying for a few öre.
        """
        start = datetime(2024, 1, 1, 0, 0)
        # With charge_power_kw=10, duration=1h: total_cost = round(spot * 1.25 * 10, 2)
        # _cost_at_start rounds total_cost to 2 decimals before sort-rounding to 1.
        # Hour 0: 1.038 * 12.5 = 12.975 -> round(_, 2) = 12.97 -> round_kr = 13.0
        # Hour 1: 1.04  * 12.5 = 13.000 -> round(_, 2) = 13.00 -> round_kr = 13.0
        # Hour 2: 1.0432 * 12.5 = 13.04 -> round(_, 2) = 13.04 -> round_kr = 13.0
        # Hour 3: 1.044 * 12.5 = 13.05  -> round(_, 2) = 13.05 -> round_kr = 13.1
        values = [1.038, 1.04, 1.0432, 1.044] + [2.0] * 20
        prices = make_prices(start, values)

        periods = find_periods_single(
            prices=prices,
            duration=1.0,
            deadline=datetime(2024, 1, 1, 23, 5),
            cutoff=datetime(2023, 12, 31, 23, 5),
            fees_inc_vat=0.0,
            vat_multiplier=1.25,
            charge_power_kw=10.0,
        )

        # Hours 0 (12.97), 1 (13.00), 2 (13.04) all round_kr to 13.0
        # They should appear in start-time order: hour 0, 1, 2
        top_three = periods[:3]
        assert top_three[0].start.hour == 0
        assert top_three[1].start.hour == 1
        assert top_three[2].start.hour == 2

    def test_half_rounds_up(self):
        """Away-from-zero rounding: 12.75 rounds to 12.8, not 12.7 (banker's rounding)."""
        start = datetime(2024, 1, 1, 0, 0)
        # Hour 0: (1.02 * 1.25 + 0) * 10 = 12.75 -> 12.8 (away-from-zero)
        # Hour 1: (0.96 * 1.25 + 0) * 10 = 12.00 -> 12.0
        values = [1.02, 0.96] + [2.0] * 22
        prices = make_prices(start, values)

        periods = find_periods_single(
            prices=prices,
            duration=1.0,
            deadline=datetime(2024, 1, 1, 23, 5),
            cutoff=datetime(2023, 12, 31, 23, 5),
            fees_inc_vat=0.0,
            vat_multiplier=1.25,
            charge_power_kw=10.0,
        )

        # Hour 1 (12.0) should come before hour 0 (12.8)
        assert periods[0].start.hour == 1
        assert periods[1].start.hour == 0

    def test_eur_rounds_to_two_decimals(self):
        """EUR uses 2-decimal precision: 12.975 -> 12.98, not 13.0."""
        assert round_kr(12.975, "EUR") == 12.98
        assert round_kr(12.975, "SEK") == 13.0

    def test_sek_half_up_one_decimal(self):
        """SEK rounds 12.95 -> 13.0 (away-from-zero at 1 decimal)."""
        assert round_kr(12.95, "SEK") == 13.0
        assert round_kr(12.94, "SEK") == 12.9

    def test_overlap_increases_slots(self):
        start = datetime(2024, 1, 1, 0, 0)
        prices = make_prices(start, [1.0] * 10)

        # Without overlap: 2 hour charging -> 2 slots
        periods_alone = find_periods_single(
            prices,
            2.0,
            datetime(2024, 1, 1, 10, 5),
            datetime(2023, 12, 31, 23, 5),
            0.0,
            1.25,
            11.0,
        )

        # With overlap in hours 0-4: effective rate halved -> needs 4 slots
        other_window = (datetime(2024, 1, 1, 0, 0), datetime(2024, 1, 1, 4, 0))
        periods_overlap = find_periods_single(
            prices,
            2.0,
            datetime(2024, 1, 1, 10, 5),
            datetime(2023, 12, 31, 23, 5),
            0.0,
            1.25,
            11.0,
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
        v1 = make_vehicle(
            "Car1", 0, 100, battery_kwh=22, charge_power_kw=11, deadline=datetime(2024, 1, 2, 7, 0)
        )
        v2 = make_vehicle(
            "Car2", 0, 100, battery_kwh=22, charge_power_kw=11, deadline=datetime(2024, 1, 2, 7, 0)
        )

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
        v1 = make_vehicle(
            "Car1", 0, 100, battery_kwh=22, charge_power_kw=11, deadline=datetime(2024, 1, 2, 7, 0)
        )
        v2 = make_vehicle(
            "Car2", 0, 100, battery_kwh=22, charge_power_kw=11, deadline=datetime(2024, 1, 2, 7, 0)
        )

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

    def test_joint_prefers_earliest_start_at_same_rounded_cost(self):
        """Joint optimization picks the earlier combo when costs round to the same value.

        Three cheap slots: hour 2 (0.52), hour 6 (0.49), hour 10 (0.48).
        All other hours are expensive (10.0). Each car needs 1h.
        vat=1.0, power=1 kW, battery=1 kWh -> total_cost per car = spot.

        Non-overlap combos (total_cost = spotA + spotB):
          {2, 6}:  0.52 + 0.49 = 1.01 -> rounds to 1.0, earliest=2
          {2, 10}: 0.52 + 0.48 = 1.00 -> rounds to 1.0, earliest=2
          {6, 10}: 0.49 + 0.48 = 0.97 -> rounds to 1.0, earliest=6

        Without rounding: {6, 10} wins (exact cost 0.97 is lowest).
        With 1-decimal rounding: all round to 1.0, earliest=2 wins -> {2, 6}.
        """
        now = datetime(2024, 1, 1, 0, 0)
        values = [10.0] * 24
        values[2] = 0.52
        values[6] = 0.49
        values[10] = 0.48
        prices = make_prices(datetime(2024, 1, 1, 0, 0), values)

        # Each needs 1h: (100-0)/100 * 1 / 1 = 1.0h, cost = spot (vat=1.0, power=1)
        v1 = make_vehicle(
            "Car1",
            0,
            100,
            battery_kwh=1,
            charge_power_kw=1,
            deadline=datetime(2024, 1, 2, 7, 0),
            vat_multiplier=1.0,
        )
        v2 = make_vehicle(
            "Car2",
            0,
            100,
            battery_kwh=1,
            charge_power_kw=1,
            deadline=datetime(2024, 1, 2, 7, 0),
            vat_multiplier=1.0,
        )

        results = optimize_joint([v1, v2], prices, now)

        r1 = results["Car1"]
        r2 = results["Car2"]
        assert r1.best_period is not None
        assert r2.best_period is not None
        # One car at hour 2, the other at hour 6 — not {6, 10}
        starts = sorted([r1.best_period.start.hour, r2.best_period.start.hour])
        assert starts == [2, 6]

    def test_empty_prices(self):
        now = datetime(2024, 1, 1, 12, 0)
        v = make_vehicle("Tesla", 50, 80)
        results = optimize_joint([v], [], now)
        assert results["Tesla"].best_period is None

    def test_sequential_fallback_triggered(self, monkeypatch):
        """When combinations exceed the limit, sequential fallback is used."""
        import custom_components.ev_charge_planner.service.optimizer as opt_mod

        # Set limit very low to force fallback
        monkeypatch.setattr(opt_mod, "_MAX_JOINT_COMBINATIONS", 1)

        now = datetime(2024, 1, 1, 0, 0)
        values = [10.0] * 24
        values[2] = 0.1
        values[3] = 0.1
        values[10] = 0.1
        values[11] = 0.1
        prices = make_prices(datetime(2024, 1, 1, 0, 0), values)

        v1 = make_vehicle(
            "Car1", 0, 100, battery_kwh=22, charge_power_kw=11, deadline=datetime(2024, 1, 2, 7, 0)
        )
        v2 = make_vehicle(
            "Car2", 0, 100, battery_kwh=22, charge_power_kw=11, deadline=datetime(2024, 1, 2, 7, 0)
        )

        results = optimize_joint([v1, v2], prices, now)

        # Both should still get valid results
        assert results["Car1"].best_period is not None
        assert results["Car2"].best_period is not None
        # Sequential assigns greedily — they should not get identical windows
        assert results["Car1"].best_period.start != results["Car2"].best_period.start


class TestDeriveEntryHours:
    """Tests for derive_entry_hours()."""

    def test_standard_hourly_slots(self):
        now = datetime(2024, 1, 15, 0, 0)
        prices = make_prices(now, [1.0, 2.0, 3.0])
        assert derive_entry_hours(prices) == 1.0

    def test_30_min_slots(self):
        now = datetime(2024, 1, 15, 0, 0)
        prices = [PriceSlot(start=now + timedelta(minutes=30 * i), value=1.0) for i in range(4)]
        assert derive_entry_hours(prices) == 0.5

    def test_15_min_slots(self):
        now = datetime(2024, 1, 15, 0, 0)
        prices = [PriceSlot(start=now + timedelta(minutes=15 * i), value=1.0) for i in range(4)]
        assert derive_entry_hours(prices) == 0.25

    def test_single_price_returns_default(self):
        now = datetime(2024, 1, 15, 0, 0)
        prices = [PriceSlot(start=now, value=1.0)]
        assert derive_entry_hours(prices) == 1.0

    def test_empty_prices_returns_default(self):
        assert derive_entry_hours([]) == 1.0

    def test_duplicated_starts_returns_default(self):
        now = datetime(2024, 1, 15, 0, 0)
        prices = [PriceSlot(start=now, value=1.0), PriceSlot(start=now, value=2.0)]
        assert derive_entry_hours(prices) == 1.0

    def test_unsorted_prices_returns_default(self):
        now = datetime(2024, 1, 15, 10, 0)
        prices = [
            PriceSlot(start=now, value=1.0),
            PriceSlot(start=now - timedelta(hours=1), value=2.0),
        ]
        assert derive_entry_hours(prices) == 1.0
