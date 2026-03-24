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
# WITHOUT WARRANTIES OR ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Load ratio-metrics config so period/level totals use aggregate-then-derive.

Resolution order:
1. ratio_metrics.yaml next to the contract (explicit overrides).
2. Contract ``derived_kpis``: ratio-shaped entries produce numerator_expr /
   denominator_expr for aggregate-then-divide in hierarchy level stats.

Lives under ``semantic`` so hierarchy and stats tools can import without
loading ADK-backed agent packages.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Set

from data_analyst_agent.semantic.derived_kpi_formula import kpi_to_aggregate_ratio_parts


def get_ratio_config_from_contract_derived_kpis(
    contract: Any,
    current_metric_name: str,
) -> Optional[Dict[str, Any]]:
    """Build ratio config from contract derived_kpis when the metric is ratio-shaped."""
    derived = getattr(contract, "derived_kpis", None) or []
    if not derived:
        return None
    name = (current_metric_name or "").strip()
    by_name = {k["name"]: k for k in derived if isinstance(k, dict) and k.get("name")}
    kpi = by_name.get(name)
    if not kpi:
        return None

    base_metric_names: Set[str] = {
        m.name for m in getattr(contract, "metrics", []) if getattr(m, "column", None)
    }
    try:
        parts = kpi_to_aggregate_ratio_parts(kpi, by_name, base_metric_names)
    except Exception:
        return None
    if not parts:
        return None
    num_expr, den_expr, mult = parts
    return {
        "numerator_expr": num_expr,
        "denominator_expr": den_expr,
        "multiply": mult,
        "materiality_min_share": None,
    }


def get_ratio_config_for_metric(contract: Any, current_metric_name: str) -> Optional[Dict[str, Any]]:
    """
    If the current metric should use aggregate-then-divide, return a ratio config dict.

    Legacy column-based keys:
        numerator_metric, denominator_metric, materiality_min_share

    Contract-derived keys:
        numerator_expr, denominator_expr, multiply, materiality_min_share
    """
    name = (current_metric_name or "").strip()

    path = _resolve_ratio_metrics_path(contract)
    if path and os.path.isfile(path):
        try:
            import yaml

            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            data = None
        if data:
            min_share = data.get("materiality_min_share")
            ratio_list = data.get("ratio_metrics") or []
            for entry in ratio_list:
                if not isinstance(entry, dict):
                    continue
                if (entry.get("metric_name") or "").strip() == name:
                    num = (entry.get("numerator_metric") or "").strip()
                    den = (entry.get("denominator_metric") or "").strip()
                    if num and den:
                        return {
                            "numerator_metric": num,
                            "denominator_metric": den,
                            "materiality_min_share": float(min_share) if min_share is not None else None,
                        }

    return get_ratio_config_from_contract_derived_kpis(contract, name)


def _resolve_ratio_metrics_path(contract: Any) -> Optional[str]:
    """Resolve path to ratio_metrics.yaml next to the contract or for validation_ops."""
    if not contract:
        return None
    source = getattr(contract, "_source_path", None)
    if source and os.path.isfile(source):
        dir_path = os.path.dirname(source)
        candidate = os.path.join(dir_path, "ratio_metrics.yaml")
        if os.path.isfile(candidate):
            return candidate
    name = getattr(contract, "name", "") or ""
    if "Validation" in name or "validation_ops" in name.lower():
        here = Path(__file__).resolve().parent
        for _ in range(8):
            candidate = here / "config" / "datasets" / "validation_ops" / "ratio_metrics.yaml"
            if candidate.is_file():
                return str(candidate)
            parent = here.parent
            if parent == here:
                break
            here = parent
        for base in [Path(os.getcwd())]:
            candidate = base / "config" / "datasets" / "validation_ops" / "ratio_metrics.yaml"
            if candidate.is_file():
                return str(candidate)
    return None
