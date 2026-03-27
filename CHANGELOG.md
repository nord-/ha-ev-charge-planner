# Changelog

## [0.4.3] - 2026-03-27

### Fixed
- Deadline timezone bug: `input_datetime` values (user's local time) were interpreted as UTC, causing charge windows to extend past the configured deadline

## [0.4.2] - 2026-03-21

### Changed
- Replace 60s continuous optimization throttle with 30s startup delay — parameter changes now trigger immediate re-optimization

## [0.4.1] - 2026-03-18

### Added
- Currency-aware rounding precision: SEK/NOK/DKK rounds to 1 decimal, EUR to 2 decimals — for both sorting and display
- Vehicle state sensor attributes: `current_soc`, `target_soc`, `charge_power_kw`, `charging_enabled`, `deadline`
- Debug price diagnostics: `_debug_price_count`, `_debug_price_first`, `_debug_price_last` sensor attributes

### Fixed
- Price fetching no longer throttled — only optimization is, preventing stale price data when NordPool updates during throttle window

## [0.4.0] - 2026-03-17

### Added
- Dynamic currency: reads currency code from the NordPool sensor (`SEK`, `NOK`, `DKK` → kr; `EUR` → €) instead of hardcoding kr

### Fixed
- `ISpotPrice` interface docstring now correctly describes that implementations may hold state (e.g. last-known currency)
- `round_kr()` docstring generalized to "whole currency units" to reflect currency-agnostic use

## [0.3.1] - 2026-03-17

### Fixed
- Options flow: `vol.Optional("vehicle_index", default=None)` caused validation failure when more than one vehicle was configured — now omits default when multiple vehicles exist

## [0.3.0] - 2026-03-15

### Added
- Per-vehicle charging enabled toggle: optional `input_boolean` entity per vehicle — when off, the vehicle is excluded from optimization entirely
- Integration icon for HA dashboard

### Changed
- Periods sorted by total cost rounded to whole kronor (away-from-zero), with earliest start as tiebreaker — no point delaying charging for a few öre
- Joint optimizer combo selection uses the same rounded-cost logic for consistency

## [0.2.0] - 2026-03-14

### Added
- `periods_list_md` attribute: markdown table of all candidate windows sorted by cost
- `All sequences` attribute: dict of all candidate windows, compatible with peaqnext format
- Options flow: add or edit vehicles after initial setup via Settings → Integrations → Configure
- Fees: configurable as entity (inc VAT) or fixed value; legacy `grid_fees_ex_vat` auto-converted
- VAT: configurable percentage per vehicle
- Charge power: configurable as entity or fixed value
- SoC target: configurable as entity or fixed value

### Changed
- Renamed sensor attribute from `periods_list` to `periods_list_md`
