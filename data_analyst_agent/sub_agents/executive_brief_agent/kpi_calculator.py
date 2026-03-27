"""Compute derived KPIs from raw additive metrics for CEO briefs.

Uses the contract's derived_kpis definitions to ensure alignment with
dashboard formulas. Falls back to hardcoded KPIs when no contract is available.
"""

from __future__ import annotations

from typing import Any, Optional


def _safe_div(numerator: float, denominator: float) -> Optional[float]:
    if denominator and denominator != 0:
        return numerator / denominator
    return None


def _pct_change(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    if current is None or prior is None or prior == 0:
        return None
    return ((current - prior) / abs(prior)) * 100


def _resolve_period_token(value: Any, days_in_period: int) -> float:
    """Resolve 'period_days' magic token to runtime days_in_period value."""
    if isinstance(value, str) and value.strip().lower() == "period_days":
        return float(days_in_period)
    return float(value)


def _eval_kpi_value(
    kpi_def: dict[str, Any],
    totals: dict[str, float],
    days_in_period: int = 7,
) -> Optional[float]:
    """Evaluate a single derived KPI definition against scalar totals.

    Supports contract shapes: numerator/denominator, numerator/subtract,
    numerator/add, numerator/divide_by, with optional multiply.

    Magic token: 'period_days' in divide_by or multiply is replaced with
    days_in_period at runtime (7 for weekly, ~30 for monthly).
    """
    numerator_name = kpi_def.get("numerator", "")
    if numerator_name not in totals:
        return None
    num_val = totals[numerator_name]
    if num_val is None:
        return None

    result = float(num_val)

    # Subtract shape: numerator - subtract - subtract2
    subtract_name = kpi_def.get("subtract")
    if subtract_name:
        if subtract_name not in totals:
            return None
        result = result - float(totals[subtract_name])
    subtract2_name = kpi_def.get("subtract2")
    if subtract2_name:
        if subtract2_name not in totals:
            return None
        result = result - float(totals[subtract2_name])

    # Add shape: numerator + add
    add_name = kpi_def.get("add")
    if add_name:
        if add_name not in totals:
            return None
        result = result + float(totals[add_name])

    # Denominator shape: result / denominator
    denom_name = kpi_def.get("denominator")
    if denom_name:
        if denom_name not in totals:
            return None
        denom_val = float(totals[denom_name])
        if denom_val == 0:
            return None
        result = result / denom_val

    # Divide_by shape: result / constant (supports 'period_days' token)
    divide_by = kpi_def.get("divide_by")
    if divide_by:
        result = result / _resolve_period_token(divide_by, days_in_period)

    # Multiply shape: result * constant (supports 'period_days' token)
    multiply = kpi_def.get("multiply")
    if multiply:
        result = result * _resolve_period_token(multiply, days_in_period)

    return result


def compute_derived_kpis_from_contract(
    contract: Any,
    current_totals: dict[str, float],
    prior_totals: dict[str, float],
    days_in_period: int = 7,
) -> list[dict[str, Any]]:
    """Compute derived KPIs using the contract's derived_kpis definitions.

    This ensures KPI values match the dashboard exactly (same formulas).
    """
    derived_defs = getattr(contract, "derived_kpis", None) or []
    if not derived_defs:
        return compute_derived_kpis(current_totals, prior_totals, days_in_period)

    kpis = []

    # First pass: compute simple derived values and add to totals for chaining
    # (some KPIs reference other derived KPIs, e.g. rev_trk_day uses ttl_rev_xf_sr_amt)
    curr_extended = dict(current_totals)
    prior_extended = dict(prior_totals)

    for kpi_def in derived_defs:
        d = kpi_def if isinstance(kpi_def, dict) else kpi_def.__dict__ if hasattr(kpi_def, '__dict__') else {}
        name = d.get("name", "")
        curr_val = _eval_kpi_value(d, curr_extended, days_in_period)
        prior_val = _eval_kpi_value(d, prior_extended, days_in_period)

        # Store computed value for downstream KPIs that reference this one
        if curr_val is not None:
            curr_extended[name] = curr_val
        if prior_val is not None:
            prior_extended[name] = prior_val

        if curr_val is None:
            continue

        # Skip KPIs marked as hidden (intermediate/duplicate values)
        if d.get("brief_hidden"):
            continue

        fmt = d.get("format", "float")
        display = d.get("display_name") or d.get("brief_label") or name
        change = _pct_change(curr_val, prior_val)

        kpis.append({
            "name": name,
            "display_name": display,
            "value": curr_val,
            "prior_value": prior_val,
            "change_pct": round(change, 1) if change is not None else None,
            "format": fmt,
            "unit": "%" if fmt == "percentage" else "",
            "optimization": d.get("optimization", "maximize"),
        })

    return kpis


def compute_derived_kpis(
    current_period: dict[str, float],
    prior_period: dict[str, float],
    days_in_period: int = 7,
) -> list[dict[str, Any]]:
    """Fallback: compute hardcoded KPIs when no contract is available."""
    kpis = []

    def _add_kpi(name, display_name, current_val, prior_val, fmt="currency", unit="", optimization="maximize"):
        if current_val is None:
            return
        change = _pct_change(current_val, prior_val)
        kpis.append({
            "name": name, "display_name": display_name,
            "value": current_val, "prior_value": prior_val,
            "change_pct": round(change, 1) if change is not None else None,
            "format": fmt, "unit": unit, "optimization": optimization,
        })

    # Rev/Truck/Day
    tc = current_period.get("truck_count", 0) or 0
    tp = prior_period.get("truck_count", 0) or 0
    _add_kpi("rev_per_truck_day", "Rev/Truck/Day",
             current_period.get("ttl_rev_amt", 0) / tc if tc else None,
             prior_period.get("ttl_rev_amt", 0) / tp if tp else None)

    # Deadhead %
    dh_c = current_period.get("dh_miles", 0)
    tm_c = current_period.get("ttl_trf_mi", 0)
    dh_p = prior_period.get("dh_miles", 0)
    tm_p = prior_period.get("ttl_trf_mi", 0)
    _add_kpi("deadhead_pct", "Deadhead %",
             (dh_c / tm_c * 100) if tm_c else None,
             (dh_p / tm_p * 100) if tm_p else None,
             fmt="percentage", unit="%", optimization="minimize")

    # Orders/Truck-Day
    oc = current_period.get("ordr_cnt", 0) or 0
    op = prior_period.get("ordr_cnt", 0) or 0
    _add_kpi("orders_per_truck_day", "Orders/Truck-Day",
             oc / tc if tc else None, op / tp if tp else None, fmt="number")

    # Rev/Order
    _add_kpi("rev_per_order", "Rev/Order",
             current_period.get("ttl_rev_amt", 0) / oc if oc else None,
             prior_period.get("ttl_rev_amt", 0) / op if op else None)

    return kpis


def format_kpi_for_brief(kpi: dict[str, Any]) -> str:
    """Format a single KPI for inclusion in the brief prompt."""
    val = kpi["value"]
    change = kpi.get("change_pct")

    if kpi["format"] == "currency":
        val_str = f"${val:,.0f}" if abs(val) >= 1000 else f"${val:,.2f}"
    elif kpi["format"] == "percentage":
        val_str = f"{val:.1f}%"
    elif val < 100:
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
        val = kpi.get("value")
        if val is None or (val == 0.0 and kpi.get("format") == "percentage"):
            continue
        lines.append(f"- {format_kpi_for_brief(kpi)}")
    return "\n".join(lines)
