"""Core optimization: find cheapest charging windows.

Supports joint optimization of multiple vehicles sharing a charger.
When vehicles' charging windows overlap, effective charge rate is halved
(shared charger capacity).
"""

from __future__ import annotations

import itertools
import logging
import math
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .models import ChargePeriod, PriceSlot, VehicleResult
from .vehicle import Vehicle

_LOGGER = logging.getLogger(__name__)

_MAX_JOINT_COMBINATIONS = 100_000


def round_kr(value: float) -> float:
    """Round to whole currency units using away-from-zero rounding (e.g. 12.50 → 13)."""
    return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def derive_entry_hours(prices: list[PriceSlot]) -> float:
    """Derive the duration of each price slot from the first two entries.

    Returns 1.0 hour by default when fewer than two prices are available
    or when the derived value is non-positive (e.g. duplicated/unsorted slots).
    """
    if len(prices) > 1:
        delta = (prices[1].start - prices[0].start).total_seconds() / 3600
        if delta > 0:
            return delta
        _LOGGER.warning(
            "Non-positive slot delta (%.2f h) — prices may be unsorted/duplicated. "
            "Falling back to 1.0 h.",
            delta,
        )
    return 1.0


def calculate_cutoff(now: datetime, entry_hours: float) -> datetime:
    """Cutoff = now - entry_hours + 5min (allow current hour as valid start)."""
    return now - timedelta(hours=entry_hours) + timedelta(minutes=5)


def calculate_deadline(now: datetime, deadline_time: datetime) -> datetime:
    """If deadline has passed today, use tomorrow. Add 5 min margin."""
    deadline = deadline_time
    if now >= deadline:
        deadline = deadline + timedelta(days=1)
    return deadline + timedelta(minutes=5)


def find_periods_single(
    prices: list[PriceSlot],
    duration: float,
    deadline: datetime,
    cutoff: datetime,
    fees_inc_vat: float,
    vat_multiplier: float,
    charge_power_kw: float,
    other_windows: list[tuple[datetime, datetime]] | None = None,
) -> list[ChargePeriod]:
    """Find all possible charging periods for a single vehicle.

    Args:
        prices: Hourly price slots (today + tomorrow).
        duration: Required charging time in hours (quarter-hour resolution).
        deadline: Car must be ready by this time.
        cutoff: Earliest allowed start time.
        fees_inc_vat: Fees including VAT (kr/kWh).
        vat_multiplier: VAT multiplier (e.g. 1.25 for Swedish 25%).
        charge_power_kw: Charging power in kW.
        other_windows: Other vehicles' active charging windows for overlap calc.

    Returns:
        List of ChargePeriod sorted by total cost (cheapest first).
    """
    if duration <= 0 or not prices:
        return []

    entry_hours = derive_entry_hours(prices)

    periods: list[ChargePeriod] = []

    for i, p in enumerate(prices):
        if p.start < cutoff or p.start >= deadline:
            continue

        period = _cost_at_start(
            prices,
            i,
            duration,
            deadline,
            fees_inc_vat,
            vat_multiplier,
            charge_power_kw,
            entry_hours,
            other_windows=other_windows,
        )
        if period is not None:
            periods.append(period)

    periods.sort(key=lambda p: (round_kr(p.total_cost), p.start))
    return periods


def _vehicle_window(
    start: datetime, duration: float, entry_hours: float
) -> tuple[datetime, datetime]:
    """Calculate the time window a vehicle occupies when starting at `start`."""
    slots = math.ceil(duration / entry_hours)
    end = start + timedelta(hours=slots * entry_hours)
    return (start, end)


def _cost_at_start(
    prices: list[PriceSlot],
    start_idx: int,
    duration: float,
    deadline: datetime,
    fees_inc_vat: float,
    vat_multiplier: float,
    charge_power_kw: float,
    entry_hours: float,
    other_windows: list[tuple[datetime, datetime]] | None = None,
) -> ChargePeriod | None:
    """Calculate the cost of charging starting at a specific price slot."""
    eff_hours = 0.0
    price_sum = 0.0
    slots_used = 0
    end = None

    for j in range(start_idx, len(prices)):
        if end is not None:
            break
        q = prices[j]

        overlap_factor = 1.0
        if other_windows:
            for win_start, win_end in other_windows:
                if q.start >= win_start and q.start < win_end:
                    overlap_factor = 0.5
                    break

        eff_hours += entry_hours * overlap_factor
        price_sum += q.value * vat_multiplier + fees_inc_vat
        slots_used += 1

        if eff_hours >= duration:
            end = q.start + timedelta(hours=entry_hours)

    if end is None or end > deadline:
        return None

    avg_price = price_sum / slots_used
    total_cost = avg_price * duration * charge_power_kw
    return ChargePeriod(
        start=prices[start_idx].start,
        end=end,
        avg_price=round(avg_price, 4),
        total_cost=round(total_cost, 2),
        duration_hours=duration,
        hours_used=slots_used,
    )


def _optimize_sequential(
    prices: list[PriceSlot],
    entry_hours: float,
    vehicle_params: list[dict],
    results: dict[str, VehicleResult],
) -> dict[str, VehicleResult]:
    """Fallback: optimize vehicles one at a time, each considering prior results."""
    assigned_windows: list[tuple[datetime, datetime]] = []

    for vp in vehicle_params:
        v = vp["vehicle"]
        periods = find_periods_single(
            prices,
            v.duration_hours,
            vp["deadline"],
            vp["cutoff"],
            v.fees_inc_vat,
            v.vat_multiplier,
            v.charge_power_kw,
            other_windows=assigned_windows if assigned_windows else None,
        )
        best = periods[0] if periods else None
        results[v.name] = VehicleResult(
            vehicle_name=v.name,
            best_period=best,
            all_periods=periods,
            duration_hours=v.duration_hours,
            needs_charging=True,
        )
        if best:
            assigned_windows.append(_vehicle_window(best.start, v.duration_hours, entry_hours))

    return results


def optimize_joint(
    vehicles: list[Vehicle],
    prices: list[PriceSlot],
    now: datetime,
) -> dict[str, VehicleResult]:
    """Find optimal start times for all vehicles jointly.

    For vehicles sharing a charger, overlapping windows reduce effective
    charge rate to 0.5. This finds the combination of start times that
    minimizes total cost across all vehicles.
    """
    if not prices:
        return {v.name: VehicleResult(v.name, None) for v in vehicles}

    entry_hours = derive_entry_hours(prices)

    # Separate vehicles that need charging from those that don't
    active = [v for v in vehicles if v.needs_charging]
    results: dict[str, VehicleResult] = {}

    for v in vehicles:
        if not v.needs_charging:
            results[v.name] = VehicleResult(
                vehicle_name=v.name,
                best_period=None,
                duration_hours=0.0,
                needs_charging=False,
            )

    if not active:
        return results

    # Single vehicle — no joint optimization needed
    if len(active) == 1:
        v = active[0]
        cutoff = calculate_cutoff(now, entry_hours)
        deadline = calculate_deadline(now, v.deadline)
        periods = find_periods_single(
            prices,
            v.duration_hours,
            deadline,
            cutoff,
            v.fees_inc_vat,
            v.vat_multiplier,
            v.charge_power_kw,
        )
        results[v.name] = VehicleResult(
            vehicle_name=v.name,
            best_period=periods[0] if periods else None,
            all_periods=periods,
            duration_hours=v.duration_hours,
            needs_charging=True,
        )
        return results

    # Joint optimization: enumerate combinations of start times
    # Build candidate start indices per vehicle
    candidates_per_vehicle: list[list[int]] = []
    vehicle_params: list[dict] = []

    for v in active:
        cutoff = calculate_cutoff(now, entry_hours)
        deadline = calculate_deadline(now, v.deadline)
        indices = [i for i, p in enumerate(prices) if p.start >= cutoff and p.start < deadline]
        candidates_per_vehicle.append(indices)
        vehicle_params.append(
            {
                "vehicle": v,
                "deadline": deadline,
                "cutoff": cutoff,
            }
        )

    # Safeguard: fall back to sequential optimization if combinatorial
    # explosion would be too expensive (>100k combinations)
    total_combos = (
        math.prod(len(c) for c in candidates_per_vehicle) if candidates_per_vehicle else 0
    )
    if total_combos > _MAX_JOINT_COMBINATIONS:
        _LOGGER.warning(
            "Joint optimization skipped: %d combinations exceeds limit %d. "
            "Falling back to sequential optimization.",
            total_combos,
            _MAX_JOINT_COMBINATIONS,
        )
        return _optimize_sequential(prices, entry_hours, vehicle_params, results)

    best_total_cost = float("inf")
    best_combo: tuple[int, ...] | None = None
    best_earliest_start: datetime | None = None

    for combo in itertools.product(*candidates_per_vehicle):
        # Two-pass: first compute windows without overlap (for overlap detection),
        # then compute actual costs with overlap.
        base_windows = []
        for idx, start_idx in enumerate(combo):
            v = vehicle_params[idx]["vehicle"]
            start = prices[start_idx].start
            base_windows.append(_vehicle_window(start, v.duration_hours, entry_hours))

        # Calculate cost for each vehicle considering others' windows
        total_cost = 0.0
        valid = True
        actual_periods: list[ChargePeriod | None] = []

        for idx, start_idx in enumerate(combo):
            v = vehicle_params[idx]["vehicle"]
            deadline = vehicle_params[idx]["deadline"]
            other_wins = [w for j, w in enumerate(base_windows) if j != idx]

            period = _cost_at_start(
                prices,
                start_idx,
                v.duration_hours,
                deadline,
                v.fees_inc_vat,
                v.vat_multiplier,
                v.charge_power_kw,
                entry_hours,
                other_windows=other_wins,
            )
            if period is None:
                valid = False
                break
            actual_periods.append(period)
            total_cost += period.total_cost

        if not valid:
            continue

        rounded_cost = round_kr(total_cost)
        earliest_start = min(prices[si].start for si in combo)
        if best_combo is None:
            best_total_cost = total_cost
            best_combo = combo
            best_earliest_start = earliest_start
            continue

        rounded_best = round_kr(best_total_cost)

        if (rounded_cost, earliest_start) < (rounded_best, best_earliest_start):
            best_total_cost = total_cost
            best_combo = combo
            best_earliest_start = earliest_start

    # Build results: best_period from best_combo, all_periods for informational list
    if best_combo is not None:
        best_windows = []
        for idx, start_idx in enumerate(best_combo):
            v = vehicle_params[idx]["vehicle"]
            start = prices[start_idx].start
            best_windows.append(_vehicle_window(start, v.duration_hours, entry_hours))

        for idx, start_idx in enumerate(best_combo):
            v = vehicle_params[idx]["vehicle"]
            deadline = vehicle_params[idx]["deadline"]
            cutoff = vehicle_params[idx]["cutoff"]
            other_wins = [w for j, w in enumerate(best_windows) if j != idx]

            # best_period is computed directly from the winning combo
            best_period = _cost_at_start(
                prices,
                start_idx,
                v.duration_hours,
                deadline,
                v.fees_inc_vat,
                v.vat_multiplier,
                v.charge_power_kw,
                entry_hours,
                other_windows=other_wins,
            )

            # all_periods is an informational list (overlap based on best combo)
            all_periods = find_periods_single(
                prices,
                v.duration_hours,
                deadline,
                cutoff,
                v.fees_inc_vat,
                v.vat_multiplier,
                v.charge_power_kw,
                other_windows=other_wins,
            )
            results[v.name] = VehicleResult(
                vehicle_name=v.name,
                best_period=best_period,
                all_periods=all_periods,
                duration_hours=v.duration_hours,
                needs_charging=True,
            )
    else:
        # No valid combination found
        for vp in vehicle_params:
            v = vp["vehicle"]
            results[v.name] = VehicleResult(
                vehicle_name=v.name,
                best_period=None,
                all_periods=[],
                duration_hours=v.duration_hours,
                needs_charging=True,
            )

    return results
