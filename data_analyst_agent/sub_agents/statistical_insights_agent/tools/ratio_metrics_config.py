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
Load ratio-metrics config so period/level totals use aggregate-then-derive.
Metric names in config must match the dimension value (e.g. "Rev/Trk/Wk" in validation data).
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional


def get_ratio_config_for_metric(contract: Any, current_metric_name: str) -> Optional[Dict[str, str]]:
    """
    If the current metric is a ratio metric, return numerator and denominator metric names.

    Args:
        contract: DatasetContract (used to resolve path to ratio_metrics.yaml).
        current_metric_name: The metric dimension value (e.g. "Rev/Trk/Wk" from df["metric"]).

    Returns:
        None if not a ratio metric or config missing; else a dict with keys:
        - "numerator_metric": str
        - "denominator_metric": str
        - "materiality_min_share": float | None — exclude terminal-periods where the
          denominator's share of the network total is below this threshold.
    """
    path = _resolve_ratio_metrics_path(contract)
    if not path or not os.path.isfile(path):
        return None
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return None
    
    data = data or {}
    min_share = data.get("materiality_min_share")
    ratio_list = data.get("ratio_metrics") or []
    name = (current_metric_name or "").strip()
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
    return None


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
        # Prefer repo root from this file: pl_analyst/data_analyst_agent/.../ratio_metrics_config.py
        file_path = Path(__file__).resolve()
        for _ in range(6):
            file_path = file_path.parent
            candidate = file_path / "config" / "datasets" / "validation_ops" / "ratio_metrics.yaml"
            if candidate.is_file():
                return str(candidate)
        for base in [Path(os.getcwd())]:
            candidate = base / "config" / "datasets" / "validation_ops" / "ratio_metrics.yaml"
            if candidate.is_file():
                return str(candidate)
    return None
