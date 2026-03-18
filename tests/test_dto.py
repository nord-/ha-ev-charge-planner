"""Tests for NordPool DTO parsing and currency propagation."""

from datetime import datetime

from custom_components.ev_charge_planner.sensor import ChargePlannerSensor
from custom_components.ev_charge_planner.service.spotprice.dto import NordPoolDTO
from custom_components.ev_charge_planner.service.spotprice.nordpool import NordPoolAdapter


class MockState:
    def __init__(self, attributes):
        self.attributes = attributes


class TestNordPoolDTO:
    def test_parse_raw_today(self):
        dto = NordPoolDTO()
        dto.set_from_state(
            MockState(
                {
                    "raw_today": [
                        {
                            "start": datetime(2024, 1, 1, 0),
                            "end": datetime(2024, 1, 1, 1),
                            "value": 0.5,
                        },
                        {
                            "start": datetime(2024, 1, 1, 1),
                            "end": datetime(2024, 1, 1, 2),
                            "value": 0.7,
                        },
                    ],
                    "raw_tomorrow": [],
                    "currency": "SEK",
                }
            )
        )
        assert len(dto.today) == 2
        assert dto.today[0].value == 0.5
        assert dto.today[1].start == datetime(2024, 1, 1, 1)
        assert not dto.tomorrow_valid
        assert dto.currency == "SEK"

    def test_parse_with_tomorrow(self):
        dto = NordPoolDTO()
        dto.set_from_state(
            MockState(
                {
                    "raw_today": [
                        {"start": datetime(2024, 1, 1, i), "value": 1.0} for i in range(24)
                    ],
                    "raw_tomorrow": [
                        {"start": datetime(2024, 1, 2, i), "value": 2.0} for i in range(24)
                    ],
                    "currency": "SEK",
                }
            )
        )
        assert len(dto.today) == 24
        assert len(dto.tomorrow) == 24
        assert dto.tomorrow_valid
        assert len(dto.all_prices) == 48

    def test_empty_attributes(self):
        dto = NordPoolDTO()
        dto.set_from_state(MockState({}))
        assert dto.today == []
        assert dto.tomorrow == []
        assert not dto.tomorrow_valid

    def test_malformed_entries_skipped(self):
        dto = NordPoolDTO()
        dto.set_from_state(
            MockState(
                {
                    "raw_today": [
                        {"start": datetime(2024, 1, 1, 0), "value": 1.0},
                        {"bad_key": "no start"},
                        "not a dict",
                        {"start": datetime(2024, 1, 1, 2), "value": 3.0},
                    ],
                    "raw_tomorrow": [],
                }
            )
        )
        assert len(dto.today) == 2
        assert dto.today[0].value == 1.0
        assert dto.today[1].value == 3.0

    def test_tomorrow_single_entry_not_valid(self):
        """NordPool sometimes returns a single empty-ish entry for tomorrow."""
        dto = NordPoolDTO()
        dto.set_from_state(
            MockState(
                {
                    "raw_today": [{"start": datetime(2024, 1, 1, 0), "value": 1.0}],
                    "raw_tomorrow": [{"start": datetime(2024, 1, 2, 0), "value": 2.0}],
                }
            )
        )
        assert not dto.tomorrow_valid  # Only 1 entry — not valid
        assert len(dto.all_prices) == 1  # Only today

    def test_all_prices_includes_tomorrow_when_valid(self):
        dto = NordPoolDTO()
        dto.set_from_state(
            MockState(
                {
                    "raw_today": [
                        {"start": datetime(2024, 1, 1, i), "value": 1.0} for i in range(3)
                    ],
                    "raw_tomorrow": [
                        {"start": datetime(2024, 1, 2, i), "value": 2.0} for i in range(3)
                    ],
                }
            )
        )
        assert dto.tomorrow_valid
        all_p = dto.all_prices
        assert len(all_p) == 6
        assert all_p[0].value == 1.0
        assert all_p[3].value == 2.0

    def test_currency_from_attribute(self):
        """Currency is read from the NordPool state attribute."""
        dto = NordPoolDTO()
        dto.set_from_state(
            MockState(
                {
                    "raw_today": [{"start": datetime(2024, 1, 1, 0), "value": 1.0}],
                    "raw_tomorrow": [],
                    "currency": "EUR",
                }
            )
        )
        assert dto.currency == "EUR"

    def test_currency_defaults_to_sek(self):
        """Missing currency attribute defaults to SEK."""
        dto = NordPoolDTO()
        dto.set_from_state(
            MockState(
                {
                    "raw_today": [{"start": datetime(2024, 1, 1, 0), "value": 1.0}],
                    "raw_tomorrow": [],
                }
            )
        )
        assert dto.currency == "SEK"


class TestNordPoolAdapterCurrency:
    def test_default_currency(self):
        """Adapter defaults to SEK before first fetch."""
        adapter = NordPoolAdapter(None, test=True)
        assert adapter.currency == "SEK"


class FakeHub:
    def __init__(self, currency, result=None, prices=None):
        self._currency = currency
        self._result = result
        self._prices = prices or []

    @property
    def currency(self):
        return self._currency

    def get_result(self, vehicle_name):
        return self._result


class TestCurrencyUnit:
    """Verify currency code → display unit mapping in sensor."""

    def _make_sensor(self, currency: str) -> ChargePlannerSensor:
        hub = FakeHub(currency)
        return ChargePlannerSensor(hub, "Test", "entry_1")

    def test_sek_gives_kr(self):
        assert self._make_sensor("SEK")._currency_unit == "kr"

    def test_nok_gives_kr(self):
        assert self._make_sensor("NOK")._currency_unit == "kr"

    def test_dkk_gives_kr(self):
        assert self._make_sensor("DKK")._currency_unit == "kr"

    def test_eur_gives_euro_sign(self):
        assert self._make_sensor("EUR")._currency_unit == "\u20ac"

    def test_unknown_currency_gives_code(self):
        assert self._make_sensor("USD")._currency_unit == "USD"

    def test_lowercase_currency(self):
        assert self._make_sensor("sek")._currency_unit == "kr"

    def test_sek_cost_decimals(self):
        assert self._make_sensor("SEK")._cost_decimals == 1

    def test_eur_cost_decimals(self):
        assert self._make_sensor("EUR")._cost_decimals == 2


class TestSensorExtraAttributes:
    """Verify vehicle state attributes are exposed on the sensor."""

    def test_vehicle_state_attributes(self):
        from custom_components.ev_charge_planner.service.models import VehicleResult

        result = VehicleResult(
            vehicle_name="Tesla",
            best_period=None,
            current_soc=68.0,
            target_soc=90.0,
            charge_power_kw=11.0,
            enabled=True,
            deadline=datetime(2024, 1, 2, 15, 30),
        )
        hub = FakeHub("SEK", result=result)
        sensor = ChargePlannerSensor(hub, "Tesla", "entry_1")
        attrs = sensor.extra_state_attributes

        assert attrs["current_soc"] == 68.0
        assert attrs["target_soc"] == 90.0
        assert attrs["charge_power_kw"] == 11.0
        assert attrs["charging_enabled"] is True
        assert attrs["deadline"] == "2024-01-02T15:30:00"

    def test_disabled_vehicle_attribute(self):
        from custom_components.ev_charge_planner.service.models import VehicleResult

        result = VehicleResult(
            vehicle_name="BYD",
            best_period=None,
            enabled=False,
        )
        hub = FakeHub("SEK", result=result)
        sensor = ChargePlannerSensor(hub, "BYD", "entry_1")
        attrs = sensor.extra_state_attributes

        assert attrs["charging_enabled"] is False

    def test_no_result_omits_vehicle_attributes(self):
        hub = FakeHub("SEK", result=None)
        sensor = ChargePlannerSensor(hub, "Missing", "entry_1")
        attrs = sensor.extra_state_attributes

        assert "current_soc" not in attrs
        assert "deadline" not in attrs
