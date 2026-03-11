"""Contract metadata helpers for prompt assembly.

Provides lightweight summaries of DatasetContract objects so prompts can
reference metrics, dimensions, and hierarchy labels without hardcoding
trade-specific columns.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str):
        return [value]
    return [value]


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


def build_contract_metadata(contract: Any | None) -> Dict[str, Any]:
    """Return a JSON-serialisable metadata summary for the dataset contract."""

    if not contract:
        return {}

    metadata: Dict[str, Any] = {
        "display_name": _field(contract, "display_name") or _field(contract, "name"),
        "description": _field(contract, "description"),
        "presentation": {
            "unit": _field(_field(contract, "presentation"), "unit")
        },
        "materiality": {
            "variance_pct": _field(_field(contract, "materiality"), "variance_pct"),
            "variance_absolute": _field(_field(contract, "materiality"), "variance_absolute"),
        },
    }

    # Metrics
    metrics_info: List[Dict[str, Any]] = []
    for metric in _as_list(_field(contract, "metrics")):
        metrics_info.append(
            {
                "name": _field(metric, "name"),
                "column": _field(metric, "column"),
                "type": _field(metric, "type"),
                "format": _field(metric, "format"),
                "optimization": _field(metric, "optimization"),
                "tags": _field(metric, "tags", []),
                "description": _field(metric, "description"),
            }
        )
    metadata["metrics"] = metrics_info

    # Dimensions
    dimensions_info: List[Dict[str, Any]] = []
    for dimension in _as_list(_field(contract, "dimensions")):
        dimensions_info.append(
            {
                "name": _field(dimension, "name"),
                "column": _field(dimension, "column"),
                "role": _field(dimension, "role"),
                "description": _field(dimension, "description"),
            }
        )
    metadata["dimensions"] = dimensions_info

    # Hierarchies
    hierarchies_info: List[Dict[str, Any]] = []
    for hierarchy in _as_list(_field(contract, "hierarchies")):
        hierarchies_info.append(
            {
                "name": _field(hierarchy, "name"),
                "children": list(_field(hierarchy, "children", []) or []),
                "level_names": dict(_field(hierarchy, "level_names", {}) or {}),
                "description": _field(hierarchy, "description"),
            }
        )
    metadata["hierarchies"] = hierarchies_info

    # Time config
    time_cfg = _field(contract, "time")
    metadata["time"] = {
        "column": _field(time_cfg, "column"),
        "frequency": _field(time_cfg, "frequency"),
        "format": _field(time_cfg, "format"),
        "range_months": _field(time_cfg, "range_months"),
    }

    reporting_cfg = _field(contract, "reporting")
    metadata["reporting"] = {
        "max_drill_depth": _field(reporting_cfg, "max_drill_depth"),
        "executive_brief_drill_levels": _field(reporting_cfg, "executive_brief_drill_levels"),
        "max_scope_entities": _field(reporting_cfg, "max_scope_entities"),
        "output_format": _field(reporting_cfg, "output_format"),
    }

    metadata["capabilities"] = list(_field(contract, "capabilities", []) or [])

    return metadata


def format_contract_context(contract: Any | None) -> str:
    """Return a compact textual context block derived from the contract."""

    metadata = build_contract_metadata(contract)
    if not metadata:
        return ""

    lines: List[str] = ["", "DATASET CONTEXT (contract-derived):"]
    name = metadata.get("display_name") or "dataset"
    frequency = metadata.get("time", {}).get("frequency") or "unknown cadence"
    lines.append(f"- Name: {name} ({frequency})")

    description = metadata.get("description")
    if description:
        lines.append(f"- Description: {description.strip()}")

    metrics = metadata.get("metrics") or []
    if metrics:
        metric_labels = ", ".join(filter(None, (m.get("name") for m in metrics)))
        if metric_labels:
            lines.append(f"- Metrics: {metric_labels}")

    dimensions = metadata.get("dimensions") or []
    if dimensions:
        primary_dims = [d for d in dimensions if (d.get("role") or "").lower() == "primary"]
        if primary_dims:
            labels = ", ".join(filter(None, (d.get("name") for d in primary_dims)))
            if labels:
                lines.append(f"- Primary dimensions: {labels}")

    hierarchies = metadata.get("hierarchies") or []
    if hierarchies:
        desc = []
        for hierarchy in hierarchies[:2]:
            children = " > ".join(hierarchy.get("children") or [])
            desc.append(f"{hierarchy.get('name')}: {children}")
        if desc:
            lines.append(f"- Hierarchies: {' | '.join(desc)}")

    materiality = metadata.get("materiality", {})
    var_pct = materiality.get("variance_pct")
    var_abs = materiality.get("variance_absolute")
    if var_pct is not None or var_abs is not None:
        lines.append(
            "- Materiality: ±{:.1f}% or ±{:,.0f}".format(
                var_pct or 0.0,
                var_abs or 0.0,
            )
        )

    return "\n".join(lines) + "\n"


def format_contract_reference_block(contract: Any | None) -> str:
    """Return a deterministic plain-text reference block for prompts/tests.

    This is intentionally stable (no random sampling) so it can be used inside
    prompt templates and cached artifacts.
    """
    metadata = build_contract_metadata(contract)
    if not metadata:
        return ""

    lines: List[str] = ["CONTRACT REFERENCE BLOCK:"]

    name = metadata.get("display_name") or metadata.get("name") or "dataset"
    if name:
        lines.append(f"- Dataset: {name}")

    time_cfg = metadata.get("time") or {}
    time_bits = []
    if time_cfg.get("column"):
        time_bits.append(f"column={time_cfg['column']}")
    if time_cfg.get("frequency"):
        time_bits.append(str(time_cfg["frequency"]))
    if time_bits:
        lines.append(f"- Time: {' | '.join(time_bits)}")

    metrics = metadata.get("metrics") or []
    if metrics:
        lines.append("- Metrics:")
        for m in metrics[:12]:
            label = m.get("name") or m.get("column") or "metric"
            col = m.get("column")
            mtype = m.get("type")
            suffix = []
            if col:
                suffix.append(f"col={col}")
            if mtype:
                suffix.append(str(mtype))
            lines.append(f"  * {label}" + (f" ({'; '.join(suffix)})" if suffix else ""))

    dims = metadata.get("dimensions") or []
    if dims:
        lines.append("- Dimensions:")
        for d in dims[:20]:
            label = d.get("name") or d.get("column") or "dimension"
            col = d.get("column")
            role = d.get("role")
            suffix = []
            if col:
                suffix.append(f"col={col}")
            if role:
                suffix.append(str(role))
            lines.append(f"  * {label}" + (f" ({'; '.join(suffix)})" if suffix else ""))

    return "\n".join(lines).strip() + "\n"


__all__ = ["build_contract_metadata", "format_contract_context", "format_contract_reference_block"]
