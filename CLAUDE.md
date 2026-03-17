# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ha-ev-charge-planner** is a Home Assistant custom integration that calculates optimal EV charging schedules based on electricity spot prices. It replaces Jinja2 template sensors (`car_1_charge_period` / `car_2_charge_period` in `../hass/templates/cars.yaml` lines 160–412) with a proper Python integration, installable via HACS.

**GitHub:** https://github.com/nord-/ha-ev-charge-planner
**Reference integration:** https://github.com/nord-/hass-peaqnext (locally at `../hass-peaqnext/`)

## Commands

```bash
# Run all tests
python -m pytest tests/ -v

# Run a single test
python -m pytest tests/test_optimizer.py::TestOptimizeJoint::test_two_vehicles_avoid_overlap -v

# Format
black custom_components/ tests/
isort custom_components/ tests/
```

## Architecture

The integration follows a layered design: **HA integration layer** → **Hub coordinator** → **Optimizer engine**.

### Core algorithm (`service/optimizer.py`)

- `derive_entry_hours()` — derives slot duration from first two price entries (defaults to 1.0h)
- `find_periods_single()` — evaluates all possible charging windows for one vehicle, considering overlap with other vehicles' windows (effective rate × 0.5 on shared charger)
- `optimize_joint()` — enumerates all combinations of start times across vehicles to find the global minimum cost. Falls back to sequential optimization when combination count exceeds 100k threshold.
- `_cost_at_start()` — computes cost for a specific start slot, used by joint optimization to evaluate each combination
- `round_kr()` — away-from-zero rounding to whole kronor, used for sorting and combo selection (12.50 → 13, not banker's rounding)

**Duration formula:** `ceil((target_soc - current_soc) / 100 × battery_kWh / charge_power_kW × 4) / 4`

**Price per slot:** `nordpool_value × vat_multiplier + fees_inc_vat` (VAT configurable as %, fees from entity or fixed)

### Hub (`service/hub.py`)

Central coordinator per config entry. Listens to state changes on price sensor + all vehicle entities (SoC, target, deadline, power, fees, enabled). Throttles updates to 60s. Uses injectable `StateReader` protocol for HA state access. Manages **freeze state** via `_freeze_state` dict storing `(frozen_duration, original_period_end)` tuples — once a vehicle's charging period has started, its parameters are locked until the period ends. Expired freeze entries are pruned in `_build_vehicles()`. Deadline rolls to next day if time has already passed. Fees read from entity (inc VAT) or fixed value, with legacy `grid_fees_ex_vat` fallback (auto-converted). VAT computed from configurable percentage. Each vehicle has an optional `enabled_entity` (`input_boolean`) — when off, the vehicle is excluded from optimization (defaults to enabled if not configured).

### Spot price layer (`service/spotprice/`)

`ISpotPrice` protocol (pure fetcher — returns prices, caller stores them) → `NordPoolAdapter` implementation. Parses `raw_today`/`raw_tomorrow` attributes (list of `{start, end, value}` dicts) into `PriceSlot` objects. Hub calls `async_fetch()` and owns the price list.

### State reader (`service/state_reader.py`)

`StateReader` protocol decouples Hub from `hass.states.get()`. Default `HassStateReader` wraps HA state lookups. Enables testing with mock state readers.

### HA layer

- `sensor.py` — `ChargePlannerSensor` entity, `device_class: timestamp`, event-driven via Hub callback + initial poll
- `config_flow.py` — multi-step: add vehicle → add another? → finish. Options flow for editing vehicle config post-setup.
- `__init__.py` — creates Hub, forwards to sensor platform, registers update listener for options flow reload

## Key Design Decisions

- **Joint optimization over sequential**: Templates calculated car 1 then car 2 referencing each other. This integration solves all vehicles simultaneously.
- **Dynamic duration**: Unlike peaqnext (static duration/consumption), duration is recalculated every update from current SoC, target SoC, battery capacity, and charge power.
- **Freeze on active charging**: "Lagt kort ligger" — once the optimal start time has passed and charging is underway, the result is frozen until the period ends.
- **Cost rounding to whole kronor**: Periods are sorted/compared by total cost rounded to whole kronor (away-from-zero). At same rounded cost, earliest start wins — no point delaying for a few öre.
- **Per-vehicle charging toggle**: Optional `input_boolean` entity per vehicle. When off, the vehicle is excluded from optimization entirely.

## User's HA Setup (Context)

- **ChargeNode** wallbox (2 ports, shared power) — Tesla Model Y + BYD Dolphin
- **NordPool** `sensor.nordpool_kwh_se3_sek_3_095_0` (SE3 zone)
- Tesla SoC via TeslaMate/MQTT, BYD SoC via MQTT
- Fees template sensor `sensor.template_fees_inc_vat` (påslag + elskatt + nätavgift, inkl moms)
- Existing automations trigger on charge_period sensors to start/stop charging
- Integration only calculates optimal start time — does NOT control the charger

## Development

- Python 3.12+, Home Assistant 2024.1+
- `pytest` for testing, `black`/`isort` for formatting
- English in code/comments, Swedish in UI labels
- HACS compatible (`hacs.json` at repo root)

## Releases

When creating a GitHub release:
1. Attach `ev_charge_planner.zip` — files must be at the **root** of the zip (no parent directory). Create from inside `custom_components/ev_charge_planner/`:
   ```powershell
   Push-Location custom_components/ev_charge_planner
   Compress-Archive -Path * -DestinationPath ../../ev_charge_planner.zip -Force
   Pop-Location
   ```
2. Tag the release on the master branch commit SHA (not `origin/master` ref).

## User Preferences

- No "Co-Authored-By: Claude" in commits
- Avoid unnecessary `cd` commands — trust the working directory
- Avoid `$()` subshell substitution in bash (triggers security prompts)
- Keep responses concise, no trailing summaries
