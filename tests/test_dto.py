"""Tests for NordPool DTO parsing."""

from datetime import datetime

from custom_components.ev_charge_planner.service.spotprice.dto import NordPoolDTO


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
