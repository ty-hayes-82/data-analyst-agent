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
Cross-Metric Correlation Tool

Computes pairwise correlations across different metrics in the dataset
using contract-driven schemas (wide or long) with a validation-data fallback.
"""

import json
import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import pearsonr


_MIN_PERIODS = 6
_STRONG_CORRELATION = 0.8
_WEAK_ENTITY_THRESHOLD = 0.3
_MAX_DIMENSION_ENTITIES = max(1, int(os.environ.get("CROSS_METRIC_MAX_DIMENSION_ENTITIES", "200")))


def _prepare_metric_pivot(df: pd.DataFrame, time_col: str, metric_map: Dict[str, str]) -> pd.DataFrame:
    if df.empty or not metric_map:
        return pd.DataFrame()
    rename_map = {col: name for name, col in metric_map.items()}
    work = df[[time_col, *metric_map.values()]].copy()
    work[time_col] = pd.to_datetime(work[time_col], errors="coerce")
    work = work.dropna(subset=[time_col])
    if work.empty:
        return pd.DataFrame()
    grouped = work.groupby(time_col)[list(metric_map.values())].sum().sort_index()
    return grouped.rename(columns=rename_map)


def _build_long_form_pivot(
    df: pd.DataFrame,
    time_col: str,
    metric_col: str,
    value_col: str,
    metric_names: List[str],
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df[[time_col, metric_col, value_col]].copy()
    work[time_col] = pd.to_datetime(work[time_col], errors="coerce")
    work = work.dropna(subset=[time_col])
    if work.empty:
        return pd.DataFrame()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce").fillna(0)
    work[metric_col] = work[metric_col].astype(str)
    work = work[work[metric_col].isin(metric_names)]
    if work.empty:
        return pd.DataFrame()
    pivot = (
        work.pivot_table(index=time_col, columns=metric_col, values=value_col, aggfunc="sum")
        .sort_index()
        .rename_axis(None, axis=1)
    )
    ordered_cols = [name for name in metric_names if name in pivot.columns]
    return pivot[ordered_cols]


def _filter_valid_metrics(pivot: pd.DataFrame) -> pd.DataFrame:
    if pivot.empty:
        return pivot
    valid_cols: List[str] = []
    for column in pivot.columns:
        series = pivot[column]
        if series.notna().sum() < _MIN_PERIODS:
            continue
        if series.std() == 0:
            continue
        valid_cols.append(column)
    return pivot[valid_cols]


def _resolve_metric_dimension(contract) -> Optional[str]:
    for dim in getattr(contract, "dimensions", []) or []:
        name = (dim.name or "").lower()
        if name == "metric" or "metric" in name:
            return dim.column
        if any("metric" in tag.lower() for tag in dim.tags):
            return dim.column
    return None


async def compute_cross_metric_correlation(
    min_r: float = 0.5,
    max_p: float = 0.10,
    include_derived: bool = True,
    per_dimension: bool = False,
    pre_resolved: Optional[dict] = None,
) -> str:
    """Compute pairwise correlations across contract-defined metrics."""

    from ...data_cache import resolve_data_and_columns

    try:
        if pre_resolved:
            ctx = pre_resolved["ctx"]
            df_source = pre_resolved.get("df") or getattr(ctx, "df", None)
            time_col = pre_resolved.get("time_col") or (ctx.contract.time.column if ctx and ctx.contract and ctx.contract.time else None)
        else:
            df_source, time_col, _metric_col, _grain_col, _name_col, ctx = resolve_data_and_columns("CrossMetricCorrelation")
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, indent=2)

    if df_source is None or ctx is None or not ctx.contract:
        return json.dumps({"error": "No dataset contract available"}, indent=2)

    contract = ctx.contract
    time_col = time_col or (contract.time.column if contract.time else None)
    if not time_col:
        return json.dumps({"error": "Contract is missing a time column"}, indent=2)

    metric_defs = [
        m
        for m in contract.metrics
        if (include_derived or (m.type or "").lower() not in ("derived", "ratio")) and m.column
    ]
    metric_names = [m.name for m in metric_defs]
    if len(metric_names) <= 1:
        return json.dumps({"skipped": True, "reason": "Single-metric dataset"}, indent=2)

    dimension_col = None
    dimension_label = "entity"
    if getattr(ctx, "primary_dimension", None):
        dimension_col = ctx.primary_dimension.column
        dimension_label = ctx.primary_dimension.name or dimension_label

    unique_columns = {m.column for m in metric_defs if m.column}
    use_wide_mode = len(unique_columns) > 1 and all(col in df_source.columns for col in unique_columns)
    metric_dim_col = _resolve_metric_dimension(contract)
    value_col = next(iter(unique_columns), None)

    entity_frame: Optional[pd.DataFrame] = None
    metric_map: Dict[str, str] = {}
    metric_pivot: pd.DataFrame = pd.DataFrame()
    source_mode = "wide" if use_wide_mode else "long"

    if use_wide_mode:
        metric_map = {m.name: m.column for m in metric_defs if m.column in df_source.columns}
        required_cols = {time_col, *metric_map.values()}
        if dimension_col and dimension_col in df_source.columns:
            required_cols.add(dimension_col)
        work_df = df_source[list(required_cols)].copy()
        for column in metric_map.values():
            work_df[column] = pd.to_numeric(work_df[column], errors="coerce").fillna(0)
        metric_pivot = _prepare_metric_pivot(work_df, time_col, metric_map)
        entity_frame = work_df
    else:
        long_df = None
        candidate_cols = {time_col, value_col}
        if metric_dim_col:
            candidate_cols.add(metric_dim_col)
        if candidate_cols.issubset(df_source.columns):
            long_df = df_source[list(candidate_cols | ({dimension_col} if dimension_col in df_source.columns else set()))].copy()
            metric_cardinality = long_df[metric_dim_col].nunique() if metric_dim_col else 0
            if metric_cardinality < len(metric_names):
                long_df = None
        if long_df is None:
            try:
                from ....tools.validation_data_loader import load_validation_data as _load_validation_data

                long_df = _load_validation_data(metric_filter=metric_names)
            except Exception:
                long_df = None
        if long_df is None or metric_dim_col is None:
            return json.dumps({"error": "Unable to resolve long-form metric data"}, indent=2)
        if time_col not in long_df.columns or value_col not in long_df.columns or metric_dim_col not in long_df.columns:
            return json.dumps({"error": "Long-form data missing required columns"}, indent=2)
        if dimension_col and dimension_col not in long_df.columns:
            per_dimension = False
        entity_frame = long_df[[time_col, metric_dim_col, value_col] + ([dimension_col] if per_dimension and dimension_col in long_df.columns else [])].copy()
        metric_pivot = _build_long_form_pivot(entity_frame, time_col, metric_dim_col, value_col, metric_names)

    metric_pivot = _filter_valid_metrics(metric_pivot)
    if metric_pivot.empty or len(metric_pivot.index) < _MIN_PERIODS:
        return json.dumps({"skipped": True, "reason": "Insufficient periods for correlation"}, indent=2)

    cols = metric_pivot.columns
    n = len(cols)
    corr_matrix = np.zeros((n, n))
    p_matrix = np.zeros((n, n))
    significant_pairs: List[Dict[str, Any]] = []

    def classify_pair(m_a: str, m_b: str, r_val: float) -> tuple[str, bool, Optional[str]]:
        classification = "strong" if abs(r_val) >= _STRONG_CORRELATION else "moderate"
        direction = "positive" if r_val > 0 else "negative"
        label = f"{classification}_{direction}"

        metric_a = contract.get_metric(m_a)
        metric_b = contract.get_metric(m_b)
        expected = False
        relationship = None

        deps_a = (metric_a.depends_on or []) + (metric_a.derived_from or [])
        deps_b = (metric_b.depends_on or []) + (metric_b.derived_from or [])
        if m_b in deps_a or m_a in deps_b:
            expected = True
            relationship = f"{m_a if m_b in deps_a else m_b} is derived from {m_b if m_b in deps_a else m_a}"

        if metric_a.pvm_role and metric_b.pvm_role:
            roles = {metric_a.pvm_role, metric_b.pvm_role}
            if "total" in roles and ("price" in roles or "volume" in roles):
                expected = True
                relationship = f"PVM relationship: {metric_a.pvm_role} vs {metric_b.pvm_role}"

        return label, expected, relationship

    for i in range(n):
        for j in range(n):
            if i == j:
                corr_matrix[i, j] = 1.0
                p_matrix[i, j] = 0.0
                continue

            series_i = metric_pivot.iloc[:, i]
            series_j = metric_pivot.iloc[:, j]
            valid_mask = ~(series_i.isna() | series_j.isna())
            if valid_mask.sum() < _MIN_PERIODS:
                corr_matrix[i, j] = 0.0
                p_matrix[i, j] = 1.0
                continue

            r_val, p_val = pearsonr(series_i[valid_mask], series_j[valid_mask])
            corr_matrix[i, j] = r_val
            p_matrix[i, j] = p_val

            if i < j and abs(r_val) >= min_r and p_val <= max_p:
                m_a, m_b = cols[i], cols[j]
                classification, expected, relationship = classify_pair(m_a, m_b, r_val)
                significant_pairs.append(
                    {
                        "metric_a": m_a,
                        "metric_b": m_b,
                        "r": round(float(r_val), 4),
                        "p_value": round(float(p_val), 6),
                        "classification": classification,
                        "expected": expected,
                        "relationship": relationship,
                    }
                )

    dimension_outliers: List[Dict[str, Any]] = []
    if (
        per_dimension
        and dimension_col
        and entity_frame is not None
        and dimension_col in entity_frame.columns
        and significant_pairs
    ):
        entity_frame[dimension_col] = entity_frame[dimension_col].astype(str)
        entity_counts = entity_frame[dimension_col].value_counts()
        entities = list(entity_counts.index[:_MAX_DIMENSION_ENTITIES])
        for entity in entities:
            subset = entity_frame[entity_frame[dimension_col] == entity]
            if subset.empty:
                continue
            if source_mode == "wide":
                entity_subset = subset.copy()
                entity_pivot = _prepare_metric_pivot(entity_subset, time_col, metric_map)
                if not entity_pivot.empty:
                    entity_pivot = entity_pivot[[c for c in cols if c in entity_pivot.columns]]
            else:
                if metric_dim_col not in subset.columns:
                    continue
                entity_subset = subset[subset[metric_dim_col].isin(cols)]
                entity_pivot = _build_long_form_pivot(entity_subset, time_col, metric_dim_col, value_col, list(cols))
            if entity_pivot.empty:
                continue
            for pair in significant_pairs:
                m_a = pair["metric_a"]
                m_b = pair["metric_b"]
                if m_a not in entity_pivot.columns or m_b not in entity_pivot.columns:
                    continue
                aligned = entity_pivot[[m_a, m_b]].dropna()
                if len(aligned) < _MIN_PERIODS:
                    continue
                term_r, _ = pearsonr(aligned[m_a], aligned[m_b])
                pop_r = pair["r"]
                if (
                    abs(pop_r) >= _STRONG_CORRELATION
                    and (
                        abs(term_r) < _WEAK_ENTITY_THRESHOLD
                        or np.sign(term_r) != np.sign(pop_r)
                    )
                ):
                    dimension_outliers.append(
                        {
                            "dimension_label": dimension_label,
                            "dimension_value": entity,
                            "metric_a": m_a,
                            "metric_b": m_b,
                            "r": round(float(term_r), 4),
                            "population_r": round(float(pop_r), 4),
                            "deviation": f"Correlation breakdown — {m_a} decoupled from {m_b} at this {dimension_label}",
                        }
                    )
        dimension_outliers = dimension_outliers[:20]

    result = {
        "matrix": {
            "metrics": list(cols),
            "correlations": corr_matrix.tolist(),
            "p_values": p_matrix.tolist(),
        },
        "significant_pairs": significant_pairs,
        "unexpected_pairs": [p for p in significant_pairs if not p["expected"]],
        "dimension_outliers": dimension_outliers,
        "summary": {
            "metrics_analyzed": len(cols),
            "significant_pairs": len(significant_pairs),
            "unexpected_pairs": len([p for p in significant_pairs if not p["expected"]]),
            "dimension_outliers": len(dimension_outliers),
            "dimension_label": dimension_label,
            "source_mode": source_mode,
        },
    }

    return json.dumps(result, indent=2)
