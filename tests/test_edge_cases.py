"""Edge case tests for optimizer and vehicle."""

from datetime import UTC, datetime, timedelta

from custom_components.ev_charge_planner.service.models import PriceSlot
from custom_components.ev_charge_planner.service.optimizer import (
    find_periods_single,
    optimize_joint,
)
from custom_components.ev_charge_planner.service.vehicle import Vehicle


def make_prices(start, values):
    return [PriceSlot(start=start + timedelta(hours=i), value=v) for i, v in enumerate(values)]


def make_vehicle(name, current_soc, target_soc, **kwargs):
    defaults = dict(
        battery_capacity_kwh=60,
        charge_power_kw=11,
        deadline=datetime(2024, 1, 1, 7, 0),
        grid_fees_ex_vat=0.0,
    )
    defaults.update(kwargs)
    return Vehicle(name=name, current_soc=current_soc, target_soc=target_soc, **defaults)


class TestEdgeCases:
    def test_all_prices_outside_window(self):
        """No candidate starts within cutoff-deadline range."""
        prices = make_prices(datetime(2024, 1, 1, 0, 0), [1.0] * 24)
        # Cutoff (23:05) is after deadline (01:05), so no valid start exists
        periods = find_periods_single(
            prices,
            2.0,
            deadline=datetime(2024, 1, 1, 1, 5),
            cutoff=datetime(2024, 1, 1, 23, 5),
            fees_ex_vat=0.0,
            vat_multiplier=1.25,
            charge_power_kw=11.0,
        )
        assert periods == []

    def test_duration_longer_than_available_hours(self):
        """Need more hours than available before deadline."""
        prices = make_prices(datetime(2024, 1, 1, 0, 0), [1.0] * 5)
        periods = find_periods_single(
            prices,
            10.0,  # need 10h but only 5 available
            deadline=datetime(2024, 1, 1, 5, 5),
            cutoff=datetime(2023, 12, 31, 23, 5),
            fees_ex_vat=0.0,
            vat_multiplier=1.25,
            charge_power_kw=11.0,
        )
        assert periods == []

    def test_zero_charge_power(self):
        v = make_vehicle("test", 50, 80, charge_power_kw=0)
        assert v.duration_hours == 0.0
        assert not v.needs_charging

    def test_negative_prices(self):
        """Negative spot prices should work (producer pays consumer)."""
        prices = make_prices(datetime(2024, 1, 1, 0, 0), [-0.5, -0.3, 0.1, 0.5])
        periods = find_periods_single(
            prices,
            1.0,
            deadline=datetime(2024, 1, 1, 5, 5),
            cutoff=datetime(2023, 12, 31, 23, 5),
            fees_ex_vat=0.0,
            vat_multiplier=1.25,
            charge_power_kw=11.0,
        )
        assert len(periods) > 0
        # Cheapest should be the most negative price
        assert periods[0].start.hour == 0
        assert periods[0].total_cost < 0

    def test_single_price_slot(self):
        """Only one hour of pricing available."""
        prices = make_prices(datetime(2024, 1, 1, 3, 0), [1.0])
        periods = find_periods_single(
            prices,
            1.0,
            deadline=datetime(2024, 1, 1, 5, 5),
            cutoff=datetime(2024, 1, 1, 2, 5),
            fees_ex_vat=0.0,
            vat_multiplier=1.25,
            charge_power_kw=11.0,
        )
        assert len(periods) == 1

    def test_joint_one_needs_charging_one_doesnt(self):
        """Mixed: one vehicle needs charging, other doesn't."""
        now = datetime(2024, 1, 1, 0, 0)
        prices = make_prices(now, [1.0] * 24)

        v1 = make_vehicle("NeedsCharge", 50, 80, deadline=datetime(2024, 1, 2, 7, 0))
        v2 = make_vehicle("Full", 80, 80, deadline=datetime(2024, 1, 2, 7, 0))

        results = optimize_joint([v1, v2], prices, now)

        assert results["NeedsCharge"].needs_charging
        assert results["NeedsCharge"].best_period is not None
        assert not results["Full"].needs_charging
        assert results["Full"].best_period is None

    def test_aware_prices_with_dtmodel_now(self):
        """NordPool prices are tz-aware; DTModel.now() must also be aware."""
        from custom_components.ev_charge_planner.service.dt_model import DTModel

        dt = DTModel()
        now = dt.now()
        assert now.tzinfo is not None, "DTModel.now() must return tz-aware datetime"

        aware_now = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        prices = make_prices(aware_now, [1.0] * 24)
        v = make_vehicle(
            "test",
            50,
            80,
            deadline=datetime(2024, 1, 2, 7, 0, tzinfo=UTC),
        )
        results = optimize_joint([v], prices, aware_now)
        assert results["test"].best_period is not None

    def test_very_small_duration(self):
        """Quarter-hour minimum charging."""
        v = make_vehicle("tiny", 99, 100, battery_capacity_kwh=44, charge_power_kw=11)
        # 0.01 * 44 / 11 = 0.04h -> ceil(0.04*4)/4 = ceil(0.16)/4 = 1/4 = 0.25
        assert v.duration_hours == 0.25
