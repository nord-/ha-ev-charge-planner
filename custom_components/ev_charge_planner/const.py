"""Constants for EV Charge Planner."""

DOMAIN = "ev_charge_planner"
PLATFORMS = ["sensor"]

# Config keys
CONF_VEHICLES = "vehicles"
CONF_VEHICLE_NAME = "name"
CONF_SOC_SENSOR = "soc_sensor"
CONF_SOC_TARGET = "soc_target"
CONF_SOC_TARGET_ENTITY = "soc_target_entity"
CONF_SOC_TARGET_FIXED = "soc_target_fixed"
CONF_BATTERY_CAPACITY = "battery_capacity"
CONF_CHARGE_POWER = "charge_power"
CONF_CHARGE_POWER_ENTITY = "charge_power_entity"
CONF_ENABLED_ENTITY = "enabled_entity"
CONF_DEADLINE_ENTITY = "deadline_entity"
CONF_PRICE_SENSOR = "price_sensor"
CONF_GRID_FEES_EX_VAT = "grid_fees_ex_vat"  # legacy
CONF_FEES_ENTITY = "fees_entity"
CONF_FEES_FIXED = "fees_fixed"
CONF_VAT_PERCENT = "vat_percent"

# Defaults
DEFAULT_VAT_PERCENT = 25.0
DEFAULT_FEES = 0.0
DEFAULT_SOC_TARGET = 80

# Hub
HUB = "hub"
STARTUP_DELAY_SECONDS = 30
