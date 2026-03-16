# EV Charge Planner for Home Assistant

A Home Assistant custom integration that calculates optimal EV charging schedules based on electricity spot prices (NordPool).

## Features

- **Spot price optimization** — finds the cheapest charging window before a configurable deadline
- **Joint optimization** — when multiple vehicles share a charger, solves all schedules simultaneously to minimize total cost (overlap = halved charge rate)
- **Dynamic duration** — recalculates charging time from current SoC, target SoC, battery capacity, and charge power
- **Freeze on active charging** — once a charging period starts, the schedule is locked until it ends

## How it works

Each vehicle gets a `sensor` with `device_class: timestamp` showing the optimal start time. Attributes:

- `periods_list_md` — markdown table of all candidate windows sorted by cost
- `All sequences` — dict of all candidate windows (compatible with peaqnext format)

The integration does **not** control the charger — it only calculates when to start. Use HA automations to trigger charging based on the sensor state.

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Install "EV Charge Planner"
3. Restart Home Assistant
4. Add the integration via Settings → Integrations

### Manual

Copy `custom_components/ev_charge_planner/` to your HA `custom_components/` directory and restart.

## Configuration

Each vehicle is configured with:

| Parameter | Description |
|---|---|
| Name | Vehicle name (e.g. "Tesla") |
| SoC sensor | Entity for current battery level (%) |
| SoC target | Entity or fixed value for charge limit (%) |
| Battery capacity | Battery size in kWh |
| Charge power | Charging power in kW (entity or fixed) |
| Deadline | `input_datetime` entity — car must be ready by this time |
| Price sensor | NordPool entity_id |
| Fees | Fees incl. VAT — entity or fixed value (kr/kWh) |
| VAT % | VAT percentage applied to spot price |

### Adding a vehicle after setup

Go to **Settings → Integrations → EV Charge Planner → Configure**. Select **Add vehicle** and fill in the vehicle details. The integration reloads automatically.

## Requirements

- Home Assistant 2024.1+
- [NordPool](https://github.com/custom-components/nordpool) integration
