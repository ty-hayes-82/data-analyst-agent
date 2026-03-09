# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Derived metric computation driven entirely by DatasetContract definitions.

For every metric declared with type="derived" the formula is evaluated against
the aggregated dataframe, producing per-period series for each ratio / derived
value.  No dataset-specific column names are hardcoded here.

Formula evaluation strategy
----------------------------
A formula like "loaded_miles / truck_count" or
"(ttl_trf_mi - ld_trf_mi) / ttl_trf_mi * 100" may reference either:
  • metric  names   (resolved via metric.column from the contract)
  • column  names   (used directly if already present in the dataframe)

We build a substitution table that covers both cases, then evaluate the
expression with pandas.eval() over each row group.
"""

import json
import re
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from ....semantic.lag_utils import resolve_effective_latest_period
from io import StringIO


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_substitution(df: pd.DataFrame, contract: Any) -> Dict[str, pd.Series]:
    """
    Return a mapping of  {token: pd.Series}  for every metric name or column
    name that appears in any derived-metric formula.

    Priority order for a metric token:
      1. The metric's declared physical column, if that column exists in df.
      2. A column whose name matches the metric name directly.
      3. A pre-computed derived column already in df.
    """
    sub: Dict[str, pd.Series] = {}

    # Seed with all columns already in df (handles both raw columns and any
    # previously-added derived columns).
    for col in df.columns:
        sub[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Overlay with contract metric → column mappings so that metric *names*
    # can also be used as formula tokens.
    for m in contract.metrics:
        if m.column and m.column in df.columns:
            sub[m.name] = pd.to_numeric(df[m.column], errors="coerce").fillna(0.0)

    return sub


def _parse_ratio_formula(formula: str, sub: Dict[str, pd.Series]) -> Optional[Tuple[str, str, bool]]:
    """
    If formula is a simple ratio (A/B or 100*A/B), return (num_key, denom_key, scale_100).
    Otherwise return None.
    """
    formula = (formula or "").strip()
    if not formula or "/" not in formula:
        return None
    # Match "A / B" or "100 * A / B" with word-boundary tokens that exist in sub
    m = re.match(r"^(?:100\s*\*\s*)?(\w+)\s*/\s*(\w+)\s*$", formula)
    if m:
        num_key = m.group(1)
        denom_key = m.group(2)
        scale_100 = formula.strip().startswith("100")
        if num_key in sub and denom_key in sub:
            return (num_key, denom_key, scale_100)
    return None


def _aggregate_then_ratio_series(
    df: pd.DataFrame,
    time_col: str,
    formula: str,
    sub: Dict[str, pd.Series],
) -> Optional[Tuple[List[Any], List[float]]]:
    """
    For ratio formulas (A/B or 100*A/B), aggregate numerator and denominator by period
    then compute ratio per period. Returns (periods_list, values_list) or None.
    """
    parsed = _parse_ratio_formula(formula, sub)
    if not parsed:
        return None
    num_key, denom_key, scale_100 = parsed
    num_series = sub[num_key]
    denom_series = sub[denom_key]
    agg_df = pd.DataFrame({
        time_col: df[time_col].values,
        "_num": pd.to_numeric(num_series.values, errors="coerce").fillna(0),
        "_den": pd.to_numeric(denom_series.values, errors="coerce").fillna(0),
    })
    period_agg = agg_df.groupby(time_col).agg({"_num": "sum", "_den": "sum"}).reset_index()
    period_agg["_ratio"] = period_agg["_num"] / period_agg["_den"].replace(0, np.nan)
    if scale_100:
        period_agg["_ratio"] = 100.0 * period_agg["_ratio"]
    period_agg = period_agg.sort_values(time_col)
    return (
        period_agg[time_col].tolist(),
        period_agg["_ratio"].replace([np.inf, -np.inf], np.nan).fillna(0.0).tolist(),
    )


def _safe_eval_formula(formula: str, sub: Dict[str, pd.Series]) -> Optional[pd.Series]:
    """
    Evaluate a formula string against a substitution dictionary.

    Returns a pd.Series or None if evaluation fails.

    The formula may contain metric / column names mixed with standard Python
    arithmetic operators.  We replace all known tokens with local variable
    references and use eval() with a restricted namespace.
    """
    # Sort tokens by length descending to avoid partial-match replacements
    # (e.g. "total_miles" before "miles").
    tokens = sorted(sub.keys(), key=len, reverse=True)

    expr = formula
    token_map: Dict[str, str] = {}
    for i, token in enumerate(tokens):
        if token in expr:
            safe_var = f"__v{i}__"
            # Use word-boundary replacement to avoid partial matches
            expr = re.sub(r"\b" + re.escape(token) + r"\b", safe_var, expr)
            token_map[safe_var] = token

    if not token_map:
        return None  # No tokens found in formula — skip

    local_ns: Dict[str, Any] = {v: sub[orig] for v, orig in token_map.items()}
    local_ns.update({"np": np, "pd": pd})

    try:
        result = eval(expr, {"__builtins__": {}}, local_ns)  # noqa: S307
        if isinstance(result, pd.Series):
            # Guard against division by zero (produces inf / nan)
            result = result.replace([np.inf, -np.inf], np.nan).fillna(0.0)
            return result
    except Exception:
        pass
    return None


def _compute_derived_series(
    df: pd.DataFrame,
    contract: Any,
    time_col: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Compute all derived metrics from the contract.

    Returns:
        ratios   – list of dicts, one per (derived metric, period) combination
        alerts   – list of human-readable degradation alert strings
    """
    derived_metrics = [
        m for m in contract.metrics
        if (m.type or "").lower() in ("derived", "ratio")
    ]

    if not derived_metrics:
        return [], []

    sub = _build_substitution(df, contract)

    ratios: List[Dict[str, Any]] = []
    alerts: List[str] = []

    degradation_threshold = float(
        (contract.policies or {}).get("degradation_threshold", 0.10)
    )

    for metric in derived_metrics:
        # If the A2A agent pre-computed this metric (column already in df), use it directly.
        if metric.name in df.columns:
            print(
                f"[DerivedMetrics] Skipping {metric.name} -- already pre-computed by A2A agent",
                flush=True,
            )
            series = pd.to_numeric(df[metric.name], errors="coerce").fillna(0.0)
        elif getattr(metric, "computed_by", None) == "a2a_agent":
            # Marked as pre-computed but column is missing -- warn and skip
            print(
                f"[DerivedMetrics] {metric.name} is marked computed_by=a2a_agent "
                f"but column is not present in data -- skipping",
                flush=True,
            )
            continue
        elif not metric.formula:
            continue
        else:
            # Prefer aggregate-then-derive for ratio formulas (sum(num)/sum(denom) per period)
            agg_ratio = _aggregate_then_ratio_series(df, time_col, metric.formula, sub)
            if agg_ratio is not None:
                periods_list, values_list = agg_ratio
            else:
                series = _safe_eval_formula(metric.formula, sub)
                if series is None:
                    continue
                series_df = pd.DataFrame({
                    time_col: df[time_col].values,
                    metric.name: series.values,
                })
                period_vals = (
                    series_df.groupby(time_col)[metric.name]
                    .mean()
                    .reset_index()
                    .sort_values(time_col)
                )
                values_list = period_vals[metric.name].tolist()
                periods_list = period_vals[time_col].tolist()

        # Degradation detection: compare most recent vs prior period
        degradation_alert: Optional[str] = None
        trend_pct: Optional[float] = None
        
        lag = 0
        if ctx and ctx.contract:
            lag = ctx.contract.get_effective_lag(metric)
            
        effective_latest, lag_window = resolve_effective_latest_period(periods_list, lag)
        
        try:
            latest_idx = periods_list.index(effective_latest)
            latest = values_list[latest_idx]
            prior = values_list[latest_idx - 1] if latest_idx > 0 else 0
        except (ValueError, IndexError):
            latest = 0
            prior = 0

        if prior != 0:
                change_pct = (latest - prior) / abs(prior)
                trend_pct = round(change_pct * 100, 2)
                if (metric.optimization == "minimize" and change_pct > degradation_threshold) or \
                   (metric.optimization == "maximize" and change_pct < -degradation_threshold):
                    direction = "increased" if change_pct > 0 else "decreased"
                    degradation_alert = (
                        f"{metric.name} {direction} by "
                        f"{abs(trend_pct):.1f}% "
                        f"({prior:.4g} → {latest:.4g}) — "
                        f"optimization goal is {metric.optimization}"
                    )
                    alerts.append(degradation_alert)

        formula_display = getattr(metric, "formula", None) or f"pre-computed ({getattr(metric, 'computed_by', 'a2a_agent')})"
        ratios.append({
            "metric": metric.name,
            "formula": formula_display,
            "optimization": metric.optimization,
            "format": metric.format,
            "periods": periods_list,
            "values": [round(v, 4) for v in values_list],
            "latest_value": round(latest, 4) if latest else None,
            "effective_latest_period": str(effective_latest),
            "lag_metadata": {
                "lag_periods": lag,
                "lag_window": [str(p) for p in lag_window]
            } if lag > 0 else None,
            "trend_pct": trend_pct,
            "degradation_alert": degradation_alert,
        })

    return ratios, alerts


# ---------------------------------------------------------------------------
# Public tool
# ---------------------------------------------------------------------------

async def compute_derived_metrics(supplementary_data_available: bool = True, pre_resolved: Optional[dict] = None) -> str:
    """
    Calculate derived metrics defined in the DatasetContract and detect degradation.

    Derived metrics (type="derived" or type="ratio") are computed from the
    pre-aggregated data already stored in the analysis context.  The formulas
    are read from the contract — no hardcoded column names.

    Returns:
        JSON string with:
          {
            "derived_metrics": [...],    # per-metric period series + trend
            "degradation_alerts": [...], # human-readable alert strings
            "summary": {
                "metrics_computed": N,
                "degradation_count": N,
                "periods_analyzed": N
            }
          }
    """
    try:
        if pre_resolved:
            df = pre_resolved["df"].copy()
            time_col = pre_resolved["time_col"]
            ctx = pre_resolved["ctx"]
        else:
            from ...data_cache import resolve_data_and_columns
            try:
                df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns(
                    "DerivedMetrics"
                )
            except ValueError as e:
                return json.dumps({"error": str(e)}, indent=2)

        if not ctx or not ctx.contract:
            return json.dumps({"error": "No dataset contract available"}, indent=2)

        if df is None or df.empty:
            return json.dumps({
                "warning": "NoData",
                "message": "No data available for derived metric computation.",
                "derived_metrics": [],
                "degradation_alerts": [],
                "summary": {"metrics_computed": 0, "degradation_count": 0, "periods_analyzed": 0},
            }, indent=2)

        periods_available = len(df[time_col].unique()) if time_col in df.columns else 0
        if periods_available < 3:
            return json.dumps({
                "warning": "InsufficientDataForRatios",
                "message": (
                    f"Ratio analysis requires at least 3 periods. "
                    f"Only {periods_available} available."
                ),
                "derived_metrics": [],
                "degradation_alerts": [],
                "summary": {"metrics_computed": 0, "degradation_count": 0, "periods_analyzed": periods_available},
            }, indent=2)

        ratios, alerts = _compute_derived_series(df, ctx.contract, time_col)

        return json.dumps({
            "derived_metrics": ratios,
            "degradation_alerts": alerts,
            "summary": {
                "metrics_computed": len(ratios),
                "degradation_count": len(alerts),
                "periods_analyzed": periods_available,
                "contract_name": ctx.contract.name,
            },
        }, indent=2)

    except Exception as e:
        import traceback
        return json.dumps({
            "error": str(e),
            "traceback": traceback.format_exc()
        }, indent=2)
