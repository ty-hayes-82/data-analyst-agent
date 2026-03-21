"""Compute derived KPIs from raw additive metrics for CEO briefs."""

from __future__ import annotations

from typing import Any


def compute_derived_kpis(
    current_period: dict[str, float],
    prior_period: dict[str, float],
    days_in_period: int = 7,
) -> list[dict[str, Any]]:
    """Compute CEO-facing KPIs from raw additive metric totals.

    Args:
        current_period: Dict of metric_name -> total for current period.
        prior_period: Dict of metric_name -> total for prior period.
        days_in_period: Number of days in the period (default 7 for weekly).

    Returns:
        List of KPI dicts with name, value, prior_value, change_pct, context.
    """
    kpis = []

    def _safe_div(num_key: str, den_key: str, data: dict) -> float | None:
        num = data.get(num_key, 0)
        den = data.get(den_key, 0)
        if den and den != 0:
            return num / den
        return None

    def _pct_change(current: float | None, prior: float | None) -> float | None:
        if current is None or prior is None or prior == 0:
            return None
        return ((current - prior) / abs(prior)) * 100

    def _add_kpi(
        name: str,
        display_name: str,
        current_val: float | None,
        prior_val: float | None,
        fmt: str = "currency",
        unit: str = "",
        optimization: str = "maximize",
    ) -> None:
        if current_val is None:
            return
        change = _pct_change(current_val, prior_val)
        kpis.append({
            "name": name,
            "display_name": display_name,
            "value": current_val,
            "prior_value": prior_val,
            "change_pct": round(change, 1) if change is not None else None,
            "format": fmt,
            "unit": unit,
            "optimization": optimization,
        })

    # Line-Haul Revenue Per Mile
    _add_kpi(
        "lrpm", "LRPM",
        _safe_div("lh_rev_amt", "ld_trf_mi", current_period),
        _safe_div("lh_rev_amt", "ld_trf_mi", prior_period),
        fmt="currency",
    )

    # Total Revenue Per Mile
    _add_kpi(
        "trpm", "TRPM",
        _safe_div("ttl_rev_amt", "ttl_trf_mi", current_period),
        _safe_div("ttl_rev_amt", "ttl_trf_mi", prior_period),
        fmt="currency",
    )

    # Revenue Per Truck Per Day
    # truck_count from data is a period total (sum of daily counts), so it already
    # represents truck-days. Divide revenue by it directly for rev/truck/day.
    truck_days_curr = current_period.get("truck_count", 0) or 0
    truck_days_prior = prior_period.get("truck_count", 0) or 0
    _add_kpi(
        "rev_per_truck_day", "Rev/Truck/Day",
        current_period.get("ttl_rev_amt", 0) / truck_days_curr if truck_days_curr else None,
        prior_period.get("ttl_rev_amt", 0) / truck_days_prior if truck_days_prior else None,
        fmt="currency",
    )

    # Miles Per Truck Per Week
    # truck_count is period-total truck-days; average fleet = truck_count / days_in_period
    avg_fleet_curr = (current_period.get("truck_count", 0) or 0) / days_in_period if days_in_period else 0
    avg_fleet_prior = (prior_period.get("truck_count", 0) or 0) / days_in_period if days_in_period else 0
    weeks = max(days_in_period / 7, 1)
    _add_kpi(
        "miles_per_truck_week", "Miles/Truck/Week",
        current_period.get("ttl_trf_mi", 0) / avg_fleet_curr / weeks if avg_fleet_curr else None,
        prior_period.get("ttl_trf_mi", 0) / avg_fleet_prior / weeks if avg_fleet_prior else None,
        fmt="number",
    )

    # Deadhead %
    _add_kpi(
        "deadhead_pct", "Deadhead %",
        (_safe_div("dh_miles", "ttl_trf_mi", current_period) or 0) * 100,
        (_safe_div("dh_miles", "ttl_trf_mi", prior_period) or 0) * 100,
        fmt="percentage", unit="%", optimization="minimize",
    )

    # Loaded %
    _add_kpi(
        "loaded_pct", "Loaded %",
        (_safe_div("ld_trf_mi", "ttl_trf_mi", current_period) or 0) * 100,
        (_safe_div("ld_trf_mi", "ttl_trf_mi", prior_period) or 0) * 100,
        fmt="percentage", unit="%",
    )

    # Idle %
    _add_kpi(
        "idle_pct", "Idle %",
        (_safe_div("idle_engn_tm", "ttl_engn_tm", current_period) or 0) * 100,
        (_safe_div("idle_engn_tm", "ttl_engn_tm", prior_period) or 0) * 100,
        fmt="percentage", unit="%", optimization="minimize",
    )

    # Orders Per Truck
    _add_kpi(
        "orders_per_truck", "Orders/Truck",
        _safe_div("ordr_cnt", "truck_count", current_period),
        _safe_div("ordr_cnt", "truck_count", prior_period),
        fmt="number",
    )

    # Revenue Per Order
    _add_kpi(
        "rev_per_order", "Rev/Order",
        _safe_div("ttl_rev_amt", "ordr_cnt", current_period),
        _safe_div("ttl_rev_amt", "ordr_cnt", prior_period),
        fmt="currency",
    )

    # Revenue Per Mile
    _add_kpi(
        "rev_per_mile", "Rev/Mile",
        _safe_div("ttl_rev_amt", "ordr_miles", current_period),
        _safe_div("ttl_rev_amt", "ordr_miles", prior_period),
        fmt="currency",
    )

    # Fuel Efficiency (miles per gallon)
    _add_kpi(
        "fuel_efficiency", "Fuel Efficiency",
        _safe_div("ttl_trf_mi", "ttl_fuel_qty", current_period),
        _safe_div("ttl_trf_mi", "ttl_fuel_qty", prior_period),
        fmt="number", unit="mi/gal",
    )

    return kpis


def format_kpi_for_brief(kpi: dict[str, Any]) -> str:
    """Format a single KPI for inclusion in the brief prompt.

    Returns a string like: "LRPM $2.48, +1.9%"
    """
    val = kpi["value"]
    change = kpi.get("change_pct")

    if kpi["format"] == "currency":
        val_str = f"${val:,.2f}"
    elif kpi["format"] == "percentage":
        val_str = f"{val:.1f}%"
    elif val < 100:
        # Small values (ratios, efficiency) get 1 decimal
        val_str = f"{val:,.1f}"
    else:
        val_str = f"{val:,.0f}"

    if kpi.get("unit") and kpi["format"] != "percentage":
        val_str += f" {kpi['unit']}"

    if change is not None:
        sign = "+" if change >= 0 else ""
        return f"{kpi['display_name']} {val_str}, {sign}{change:.1f}%"
    return f"{kpi['display_name']} {val_str}"


def format_kpis_block(kpis: list[dict[str, Any]]) -> str:
    """Format all KPIs as a text block for the brief prompt."""
    lines = []
    for kpi in kpis:
        lines.append(f"- {format_kpi_for_brief(kpi)}")
    return "\n".join(lines)
