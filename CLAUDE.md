# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ha-ev-charge-planner** is a Home Assistant custom integration that calculates optimal EV charging schedules based on electricity spot prices. It replaces complex Jinja2 template sensors with a proper Python integration, installable via HACS.

**Status:** Early development — building from scratch.

**GitHub:** https://github.com/nord-/ha-ev-charge-planner
**Reference integration:** https://github.com/nord-/hass-peaqnext (locally at `../hass-peaqnext/`)
**User's HA config:** locally at `../hass/` (the templates being replaced are in `../hass/templates/cars.yaml` lines 160–412)

## What This Integration Must Do

Replace the Jinja2 template sensors `sensor.car_1_charge_period` and `sensor.car_2_charge_period` from the user's HA config. These sensors calculate the cheapest time to start charging each EV before a deadline, considering NordPool spot prices.

### Core Algorithm (must replicate this logic)

1. **Get prices**: NordPool `raw_today` + `raw_tomorrow` (list of `{start, value}` dicts)
2. **Deadline**: User-configured time (e.g. "07:00") — if already passed today, use tomorrow. Add 5 min margin.
3. **Cutoff**: `now() - entry_hours + 5min` (allow current hour as valid start)
4. **Duration**: `ceil((target_soc - current_soc) / 100 × battery_kWh / charge_power_kW × 4) / 4` (rounded up to nearest quarter hour)
5. **For each possible start hour** (cutoff → deadline):
   - Walk forward hour by hour accumulating time
   - If hour **overlaps another vehicle's charging window** → effective time × 0.5 (shared charger capacity)
   - Accumulate price: `(nordpool_value + grid_fees_ex_vat) × 1.25` (Swedish VAT)
   - Stop when accumulated effective hours >= duration
6. **Total cost** = average_price × duration × charge_power_kW
7. **Select** the start time with lowest total cost

### Key Improvement Over Templates

The templates calculate sequentially (car 1 references car 2's period and vice versa). The integration should do **joint optimization** — solve both vehicles' schedules simultaneously to find the global optimum.

### Sensor Output

Each vehicle gets a sensor with:
- **State**: `device_class: timestamp` — the optimal start time (or `unavailable` if no charging needed)
- **Attribute `periods_list`**: All possible charging windows sorted by cost (markdown table or structured list)

## Architecture

```
custom_components/ev_charge_planner/
├── __init__.py          # Entry point, setup Hub, register services
├── config_flow.py       # UI config: add vehicles with battery/power/SoC entities
├── const.py             # Domain name, config keys, defaults
├── sensor.py            # PlannerSensor entity (timestamp + periods_list)
├── manifest.json        # after_dependencies: [nordpool], iot_class: calculated
├── strings.json         # UI strings (English)
├── translations/
│   └── en.json
└── service/
    ├── hub.py           # Central coordinator: manages vehicles, listens to price changes
    ├── optimizer.py     # Core: finds cheapest charging windows (joint optimization)
    ├── vehicle.py       # Vehicle dataclass: SoC, battery, power, deadline
    └── spotprice/
        ├── factory.py   # Selects NordPool or EnergiDataService adapter
        └── nordpool.py  # Fetches prices from nordpool integration state
```

## Config Flow Design

Per vehicle, the user configures:
- **Name** (e.g. "Tesla", "Dolphin")
- **SoC sensor** entity_id (current battery level)
- **SoC target** entity_id or fixed value (charge limit)
- **Battery capacity** kWh (number)
- **Charge power** kW (or high/low season entities)
- **Deadline** entity_id (input_datetime) — "car must be ready by"
- **Price sensor** entity_id (NordPool sensor)
- **Grid fees ex VAT** (number, kr/kWh)

## Patterns to Borrow from peaqnext

The reference integration `hass-peaqnext` (in `../hass-peaqnext/`) has good patterns:

**Use these:**
- `SpotPriceFactory` + adapter pattern for price sources (`service/spotprice/`)
- Hub as central coordinator with event listeners and 60s throttling (`service/hub.py`)
- `PeriodModel` as dataclass for results (`service/models/period_model.py`)
- `manifest.json` structure (`after_dependencies`, `iot_class: calculated`)
- Test patterns with mocked datetime (`DTModel`)

**Don't copy these** (not relevant for EV charging):
- Consumption patterns (flat/peakIn/etc) — EV charging is always flat
- "Search window in hours" — we use deadline instead
- Single-sensor-at-a-time config flow — we configure vehicles

## User's Current HA Setup (Context)

The user (Rickard) runs HA with:
- **ChargeNode** wallbox (Modbus TCP, 2 ports) — port 1: Tesla, port 2: BYD Dolphin
- **NordPool** integration: `sensor.nordpool_kwh_se3_sek_3_095_0` (SE3 zone)
- **TeslaMate** for Tesla SoC via MQTT
- **BYD** SoC via MQTT (`sensor.byd_dolphin_soc`)
- **Automations** that trigger on the charge_period sensors to start/stop charging via REST calls to ChargeNode cloud API

The integration does NOT need to control the charger — it only calculates the optimal start time. Existing automations handle the actual charging.

## Development Guidelines

- Python 3.12+, Home Assistant 2024.1+
- Use `pytest` + `pytest-homeassistant-custom-component` for testing
- Follow HA integration development best practices
- Swedish in UI labels where relevant, English in code/comments
- HACS compatible: include `hacs.json` at repo root
- Use `pyproject.toml` for project config (black, isort, pytest)

## User Preferences

- No "Co-Authored-By: Claude" in commits
- Avoid unnecessary `cd` commands — trust the working directory
- Avoid `$()` subshell substitution in bash (triggers security prompts)
- Keep responses concise, no trailing summaries
