"""Auto-detect dataset properties and generate a draft contract.yaml.

Scans a CSV file and infers:
- Time columns (date parsing)
- Numeric metrics (additive vs ratio)
- Categorical dimensions (cardinality analysis)
- Hierarchical relationships (parent-child nesting)
- Frequency (daily, weekly, monthly, yearly)
- Suggested materiality thresholds
"""
from __future__ import annotations

import csv
import io
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


CURRENCY_SYMBOLS = ("$", "€", "£")
CURRENCY_NAME_HINTS = ("revenue", "sales", "usd", "amount", "cost", "price", "gmv")
PERCENT_NAME_HINTS = ("pct", "percent", "ratio", "rate", "margin")

# Date formats to try, ordered by specificity
DATE_FORMATS = [
    ("%Y-%m-%d %H:%M:%S", "datetime"),
    ("%Y-%m-%dT%H:%M:%S", "datetime"),
    ("%Y-%m-%d", "date"),
    ("%m/%d/%Y", "date"),
    ("%d/%m/%Y", "date"),
    ("%Y/%m/%d", "date"),
    ("%m-%d-%Y", "date"),
    ("%B %d, %Y", "date"),
    ("%b %d, %Y", "date"),
    ("%Y-%m", "month"),
    ("%Y", "year"),
]


def _clean_numeric_token(value: str) -> str:
    if value is None:
        return ""
    cleaned = value.replace(",", "").strip()
    for sym in CURRENCY_SYMBOLS:
        cleaned = cleaned.replace(sym, "")
    cleaned = cleaned.replace("%", "")
    return cleaned.strip()


def _sample_rows(file_path: str, max_rows: int = 5000) -> tuple[list[str], list[dict]]:
    """Read up to max_rows from a CSV, return (headers, rows_as_dicts)."""
    path = Path(file_path)
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = []
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            rows.append(row)
    return headers, rows


def _try_parse_date(value: str) -> tuple[str, str] | None:
    """Try parsing a string as a date. Returns (format, granularity) or None."""
    value = value.strip()
    if not value or len(value) < 4:
        return None
    for fmt, granularity in DATE_FORMATS:
        try:
            datetime.strptime(value, fmt)
            return fmt, granularity
        except ValueError:
            continue
    return None


def _is_numeric(value: str) -> bool:
    """Check if a string is numeric (int or float)."""
    try:
        cleaned = _clean_numeric_token(value)
        if not cleaned:
            return False
        float(cleaned)
        return True
    except (ValueError, AttributeError):
        return False


def _detect_column_types(headers: list[str], rows: list[dict]) -> dict[str, dict]:
    """Analyze each column and classify its type."""
    results = {}
    for col in headers:
        values = [r.get(col, "").strip() for r in rows if r.get(col, "").strip()]
        if not values:
            results[col] = {"type": "empty", "non_null_count": 0}
            continue

        sample = values[:200]
        non_null = len(values)
        total = len(rows)
        fill_rate = non_null / total if total > 0 else 0

        # Check for date
        date_hits = 0
        detected_format = None
        detected_granularity = None
        for v in sample[:50]:
            parsed = _try_parse_date(v)
            if parsed:
                date_hits += 1
                if not detected_format:
                    detected_format, detected_granularity = parsed
        date_ratio = date_hits / min(len(sample), 50) if sample else 0

        if date_ratio > 0.8 and detected_format:
            results[col] = {
                "type": "time",
                "format": detected_format,
                "granularity": detected_granularity,
                "non_null_count": non_null,
                "fill_rate": fill_rate,
            }
            continue

        # Check for numeric
        numeric_count = sum(1 for v in sample if _is_numeric(v))
        numeric_ratio = numeric_count / len(sample) if sample else 0

        if numeric_ratio > 0.8:
            name_lower = col.lower()
            currency_hits = sum(1 for v in sample if v.strip().startswith(CURRENCY_SYMBOLS))
            percent_hits = sum(1 for v in sample if v.strip().endswith("%"))
            is_currency = (currency_hits / len(sample) > 0.3) or any(h in name_lower for h in CURRENCY_NAME_HINTS)
            is_percentage = (percent_hits / len(sample) > 0.3) or any(h in name_lower for h in PERCENT_NAME_HINTS)

            # Parse actual values for stats
            nums = []
            for v in values[:2000]:
                try:
                    nums.append(float(_clean_numeric_token(v)))
                except (ValueError, AttributeError):
                    pass

            is_integer = all(n == int(n) for n in nums[:500]) if nums else False
            has_negatives = any(n < 0 for n in nums) if nums else False

            # Detect if it's a ratio (bounded 0-1 or 0-100, or small range)
            is_ratio = False
            if nums:
                mn, mx = min(nums), max(nums)
                if 0 <= mn and mx <= 1.01:
                    is_ratio = True
                elif 0 <= mn and mx <= 100 and statistics.stdev(nums) < 30 if len(nums) > 1 else False:
                    is_ratio = True
            if is_percentage:
                is_ratio = True

            # Detect if it could be an ID (integers with high cardinality, no pattern)
            unique_ratio = len(set(values[:1000])) / min(len(values), 1000)
            # ID heuristic: integer, very high uniqueness, small values, AND column name looks like an ID
            id_name_hints = any(h in col.lower() for h in ["id", "code", "key", "fips", "zip", "sku", "num"])
            has_wide_range = (max(nums) - min(nums)) > 1000 if nums else False
            is_likely_id = is_integer and unique_ratio > 0.95 and not has_negatives and (id_name_hints or not has_wide_range)

            results[col] = {
                "type": "numeric",
                "subtype": "id" if is_likely_id else ("ratio" if is_ratio else "additive"),
                "is_integer": is_integer,
                "has_negatives": has_negatives,
                "non_null_count": non_null,
                "fill_rate": fill_rate,
                "min": min(nums) if nums else 0,
                "max": max(nums) if nums else 0,
                "mean": statistics.mean(nums) if nums else 0,
                "unique_count": len(set(str(int(n)) if is_integer else str(n) for n in nums[:2000])),
                "is_currency": is_currency,
                "is_percentage": is_percentage,
            }
            continue

        # Categorical / text
        unique_values = set(values[:2000])
        cardinality = len(unique_values)

        results[col] = {
            "type": "categorical",
            "cardinality": cardinality,
            "non_null_count": non_null,
            "fill_rate": fill_rate,
            "sample_values": sorted(list(unique_values))[:10],
        }

    return results


def _detect_frequency(rows: list[dict], time_col: str, time_format: str) -> str:
    """Detect the time frequency (daily, weekly, monthly, yearly)."""
    dates = []
    for r in rows[:3000]:
        v = r.get(time_col, "").strip()
        if not v:
            continue
        try:
            dates.append(datetime.strptime(v, time_format))
        except ValueError:
            continue

    if len(dates) < 3:
        return "unknown"

    dates.sort()
    deltas = [(dates[i+1] - dates[i]).days for i in range(min(len(dates)-1, 500))]
    deltas = [d for d in deltas if d > 0]  # Remove same-day entries

    if not deltas:
        return "unknown"

    median_delta = sorted(deltas)[len(deltas) // 2]

    if median_delta <= 1:
        return "daily"
    elif 5 <= median_delta <= 8:
        return "weekly"
    elif 25 <= median_delta <= 35:
        return "monthly"
    elif 85 <= median_delta <= 100:
        return "quarterly"
    elif 350 <= median_delta <= 380:
        return "yearly"
    else:
        return "unknown"


def _geo_rank(name: str) -> int:
    if not name:
        return 999
    nl = name.lower()
    rank_order = [
        ("continent", 0),
        ("region", 1),
        ("country", 2),
        ("nation", 2),
        ("state", 3),
        ("province", 3),
        ("county", 4),
        ("district", 4),
        ("city", 5),
        ("metro", 5),
        ("zip", 6),
        ("postal", 6),
    ]
    for token, rank in rank_order:
        if token in nl:
            return rank
    return 999


def _detect_hierarchies(col_types: dict, rows: list[dict]) -> list[dict]:
    """Detect potential hierarchical relationships between categorical columns."""
    categoricals = [
        (col, info) for col, info in col_types.items()
        if info["type"] == "categorical" and 2 <= info["cardinality"] <= 1000
    ]

    if len(categoricals) < 2:
        return []

    # Sort by cardinality (ascending = broader/parent first)
    categoricals.sort(key=lambda x: x[1]["cardinality"])

    # Check parent-child relationships: if each child value maps to exactly one parent
    hierarchies = []
    used = set()

    for i, (parent_col, parent_info) in enumerate(categoricals):
        children = []
        for j, (child_col, child_info) in enumerate(categoricals):
            if i == j or child_col in used:
                continue
            if child_info["cardinality"] <= parent_info["cardinality"]:
                continue

            # Check if child -> parent is many-to-one
            mapping = {}
            is_hierarchy = True
            for r in rows[:3000]:
                cv = r.get(child_col, "").strip()
                pv = r.get(parent_col, "").strip()
                if not cv or not pv:
                    continue
                if cv in mapping:
                    if mapping[cv] != pv:
                        is_hierarchy = False
                        break
                else:
                    mapping[cv] = pv

            if is_hierarchy and len(mapping) >= 2:
                children.append(child_col)

        if children:
            chain = [parent_col] + children[:3]  # Max 4 levels
            hierarchies.append({
                "name": f"by_{parent_col}".lower().replace(" ", "_"),
                "description": f"Drill-down: {' -> '.join(chain)}",
                "children": chain,
                "level_names": {i: (col if i > 0 else "Total") for i, col in enumerate(["Total"] + chain)},
            })
            used.update(chain)

    # Geo-aware fallback if parent-child detection failed
    if not hierarchies:
        geo_candidates = [col for col, _ in categoricals if _geo_rank(col) < 999]
        geo_candidates = sorted(geo_candidates, key=_geo_rank)
        chain: list[str] = []
        for col in geo_candidates:
            if col not in chain:
                chain.append(col)
            if len(chain) >= 4:
                break
        if len(chain) >= 2:
            hierarchies.append({
                "name": "by_" + chain[0].lower().replace(" ", "_"),
                "description": f"Drill-down: {' -> '.join(chain)}",
                "children": chain,
                "level_names": {i: (col if i > 0 else "Total") for i, col in enumerate(["Total"] + chain)},
            })

    # If no natural hierarchy found, create a flat one from top categoricals
    if not hierarchies and len(categoricals) >= 2:
        top = [col for col, _ in categoricals[:3]]
        hierarchies.append({
            "name": "by_" + top[0].lower().replace(" ", "_"),
            "description": f"Drill-down: {' -> '.join(top)}",
            "children": top,
            "level_names": {i: (col if i > 0 else "Total") for i, col in enumerate(["Total"] + top)},
        })

    return hierarchies


def detect_contract(file_path: str) -> dict[str, Any]:
    """Scan a CSV and produce a draft contract.yaml structure.

    Returns a dict with:
      - contract: the draft contract
      - confidence: per-field confidence scores
      - warnings: list of things the user should review
    """
    headers, rows = _sample_rows(file_path, max_rows=5000)
    if not headers or not rows:
        return {"contract": {}, "confidence": {}, "warnings": ["File is empty or has no headers"]}

    col_types = _detect_column_types(headers, rows)
    warnings = []
    confidence = {}

    # --- Identify time column ---
    time_cols = [(col, info) for col, info in col_types.items() if info["type"] == "time"]
    if not time_cols:
        warnings.append("No time/date column detected. This dataset may not be a time series.")
        time_col = None
        time_format = None
        frequency = "unknown"
    else:
        # Pick the one with best fill rate
        time_col, time_info = max(time_cols, key=lambda x: x[1]["fill_rate"])
        time_format = time_info["format"]
        frequency = _detect_frequency(rows, time_col, time_format)
        confidence["time_column"] = "high" if time_info["fill_rate"] > 0.95 else "medium"
        if len(time_cols) > 1:
            warnings.append(f"Multiple date columns detected: {[c for c, _ in time_cols]}. Selected '{time_col}'.")

    # --- Identify metrics ---
    metrics = []
    for col, info in col_types.items():
        if info["type"] != "numeric":
            continue
        if info.get("subtype") == "id":
            continue  # Skip likely ID columns

        metric_type = "ratio" if info.get("subtype") == "ratio" else "additive"
        if info.get("is_percentage"):
            metric_type = "ratio"

        if info.get("is_currency"):
            fmt = "currency"
        elif info.get("is_percentage"):
            fmt = "percentage"
        elif info.get("is_integer"):
            fmt = "integer"
        else:
            fmt = "float"

        metrics.append({
            "name": col.lower().replace(" ", "_"),
            "column": col,
            "type": metric_type,
            "format": fmt,
            "optimization": "maximize",
            "tags": [],
            "description": f"Auto-detected from column '{col}'",
            "_stats": {
                "min": round(info.get("min", 0), 2),
                "max": round(info.get("max", 0), 2),
                "mean": round(info.get("mean", 0), 2),
                "unique_count": info.get("unique_count", 0),
            },
        })

    if not metrics:
        warnings.append("No numeric metric columns detected.")
    confidence["metrics"] = "high" if len(metrics) >= 1 else "low"

    # --- Identify dimensions ---
    dimensions = []
    for col, info in col_types.items():
        if info["type"] == "categorical" and info["cardinality"] >= 2:
            role = "primary" if info["cardinality"] <= 50 else "secondary"
            dimensions.append({
                "name": col.lower().replace(" ", "_"),
                "column": col,
                "role": role,
                "description": f"Categorical column with {info['cardinality']} unique values",
                "_sample_values": info.get("sample_values", []),
            })
        elif info["type"] == "time":
            dimensions.append({
                "name": col.lower().replace(" ", "_"),
                "column": col,
                "role": "time",
                "description": f"Time column ({info.get('granularity', 'date')})",
            })
        elif info["type"] == "numeric" and info.get("subtype") == "id":
            dimensions.append({
                "name": col.lower().replace(" ", "_"),
                "column": col,
                "role": "secondary",
                "description": f"Numeric ID column with {info.get('unique_count', 0)} unique values",
            })

    confidence["dimensions"] = "high" if len(dimensions) >= 2 else "medium" if dimensions else "low"

    # --- Detect hierarchies ---
    hierarchies = _detect_hierarchies(col_types, rows)
    confidence["hierarchies"] = "high" if hierarchies else "low"
    if not hierarchies:
        warnings.append("No clear hierarchical relationships detected. You may want to define these manually.")

    # --- Time range ---
    range_months = 24
    if time_col and time_format:
        dates = []
        for r in rows:
            v = r.get(time_col, "").strip()
            try:
                dates.append(datetime.strptime(v, time_format))
            except ValueError:
                continue
        if dates:
            date_range = (max(dates) - min(dates)).days
            range_months = max(1, int(date_range / 30))

    # --- Materiality thresholds ---
    if metrics:
        primary_metric = metrics[0]
        mean_val = primary_metric["_stats"]["mean"]
        materiality_abs = round(mean_val * 0.05, 2) if mean_val > 0 else 100
        materiality_pct = 8.0
    else:
        materiality_abs = 100
        materiality_pct = 8.0

    # --- Build grain ---
    grain_cols = []
    if time_col:
        grain_cols.append(time_col)
    grain_cols.extend([d["column"] for d in dimensions if d["role"] in ("primary", "secondary")][:4])

    # --- File info ---
    path = Path(file_path)
    file_size = path.stat().st_size
    row_count = len(rows)  # This is sampled, actual may be larger

    # --- Clean metrics for output (remove internal _stats) ---
    clean_metrics = []
    for m in metrics:
        cm = {k: v for k, v in m.items() if not k.startswith("_")}
        clean_metrics.append(cm)

    clean_dimensions = []
    for d in dimensions:
        cd = {k: v for k, v in d.items() if not k.startswith("_")}
        clean_dimensions.append(cd)

    # --- Assemble contract ---
    name = path.stem.replace("_", " ").replace("-", " ").title()
    contract = {
        "name": name,
        "version": "1.0.0",
        "display_name": name,
        "target_label": "Metric",
        "description": f"Auto-detected contract for {path.name}. Please review and customize.",
        "materiality": {
            "variance_pct": materiality_pct,
            "variance_absolute": materiality_abs,
        },
        "presentation": {"unit": "count"},
        "reporting": {
            "max_drill_depth": min(len(hierarchies[0]["children"]) if hierarchies else 2, 5),
            "executive_brief_drill_levels": 2,
            "max_scope_entities": 20,
            "output_format": "pdf",
        },
        "data_source": {
            "type": "csv",
            "file": file_path,
        },
        "time": {
            "column": time_col or headers[0],
            "frequency": frequency,
            "format": time_format or "%Y-%m-%d",
            "range_months": range_months,
        },
        "grain": {"columns": grain_cols},
        "metrics": clean_metrics,
        "dimensions": clean_dimensions,
        "hierarchies": hierarchies,
        "capabilities": _generate_capabilities(clean_metrics, clean_dimensions, hierarchies, frequency),
        "policies": {"degradation_threshold": 0.12},
    }

    # Metric detail for review UI
    metric_details = []
    for m, orig in zip(clean_metrics, metrics):
        metric_details.append({
            **m,
            "stats": orig.get("_stats", {}),
        })

    dimension_details = []
    for d, orig in zip(clean_dimensions, dimensions):
        dimension_details.append({
            **d,
            "sample_values": orig.get("_sample_values") if hasattr(orig, "get") else
                             [dd for dd in [dimensions[clean_dimensions.index(d)]] if "_sample_values" in dd][0].get("_sample_values", []) if any("_sample_values" in dd for dd in [dimensions[clean_dimensions.index(d)]]) else [],
        })

    return {
        "contract": contract,
        "confidence": confidence,
        "warnings": warnings,
        "file_info": {
            "name": path.name,
            "size_bytes": file_size,
            "sampled_rows": row_count,
            "total_columns": len(headers),
            "headers": headers,
        },
        "metric_details": metric_details,
        "dimension_details": [{**d, "sample_values": next((orig.get("_sample_values", []) for orig in [dimensions[i]] if "_sample_values" in orig), [])} for i, d in enumerate(clean_dimensions)],
    }


def _generate_capabilities(metrics, dimensions, hierarchies, frequency):
    """Generate a capabilities list based on detected properties."""
    caps = []
    if frequency != "unknown":
        caps.append(f"{frequency} trend analysis")
    if len(metrics) > 1:
        caps.append(f"multi-metric analysis across {len(metrics)} measures")
    elif metrics:
        caps.append(f"single-metric deep analysis on {metrics[0]['name']}")
    for h in hierarchies:
        caps.append(f"drill-down: {' -> '.join(h['children'])}")
    if any(d["role"] == "primary" for d in dimensions):
        primary_dims = [d["name"] for d in dimensions if d["role"] == "primary"]
        caps.append(f"comparative analysis across {', '.join(primary_dims)}")
    caps.append("anomaly detection and variance analysis")
    caps.append("period-over-period change tracking")
    return caps


def save_contract(contract: dict, dataset_id: str, base_dir: str = "/data/data-analyst-agent/config/datasets/csv") -> str:
    """Save a confirmed contract to disk."""
    target_dir = Path(base_dir) / dataset_id
    target_dir.mkdir(parents=True, exist_ok=True)

    contract_path = target_dir / "contract.yaml"
    with open(contract_path, "w") as f:
        yaml.dump(contract, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Also create a basic loader.yaml
    loader = {
        "type": "csv",
        "file": contract.get("data_source", {}).get("file", ""),
        "encoding": "utf-8",
        "date_columns": [contract.get("time", {}).get("column", "")],
        "numeric_columns": [m["column"] for m in contract.get("metrics", [])],
    }
    loader_path = target_dir / "loader.yaml"
    with open(loader_path, "w") as f:
        yaml.dump(loader, f, default_flow_style=False, sort_keys=False)

    return str(contract_path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python contract_detector.py <csv_file>")
        sys.exit(1)
    result = detect_contract(sys.argv[1])
    print(yaml.dump(result["contract"], default_flow_style=False, sort_keys=False))
    if result["warnings"]:
        print("\n--- WARNINGS ---")
        for w in result["warnings"]:
            print(f"  ! {w}")
    print(f"\nConfidence: {result['confidence']}")
