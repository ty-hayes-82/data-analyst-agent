"""
DatasetProfiler: auto-generate DatasetContract drafts from DataFrames.

Phase 7 (US3) of the Semantic Core.

The profiler uses heuristics to infer:
- Time column (date/period keywords, parseable as datetime)
- Metric columns (numeric, high cardinality or float)
- Dimension columns (categorical or low-cardinality numeric)
- Grain (combination that produces unique rows)
- Metric type (additive vs non_additive)
- Optimization direction

Uncertain inferences are annotated with '# REVIEW' comments (FR-010).
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
import yaml

from .models import DatasetContract, MetricDefinition, DimensionDefinition, TimeConfig, GrainConfig


# Heuristic patterns for ratio/non-additive detection
_RATIO_KEYWORDS = {"rate", "pct", "percent", "ratio", "share", "margin", "yield"}

# Heuristic patterns for optimization direction
_MINIMIZE_KEYWORDS = {"cost", "expense", "error", "latency", "churn", "defect", "loss", "debt"}
_MAXIMIZE_KEYWORDS = {"revenue", "income", "profit", "sales", "count", "requests", "orders", "utilization"}


class DatasetProfiler:
    """Analyzes a DataFrame to suggest a DatasetContract draft."""

    def __init__(self, name: str = "Draft Dataset"):
        self.name = name
        self._review_comments: List[str] = []

    def profile_dataframe(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Analyzes columns and types to guess contract components.

        Returns:
            Dict with keys: name, version, description, time, grain, metrics, dimensions.
            Contains '# REVIEW' annotations on uncertain fields.
        """
        self._review_comments = []

        time_info = self._guess_time_column(df)
        exclude_cols = [time_info["column"]] if time_info else []
        metrics = self._guess_metrics(df, exclude=exclude_cols)
        dims = self._guess_dimensions(
            df, exclude=exclude_cols + [m["column"] for m in metrics]
        )
        grain = self._guess_grain(df, time_info, dims)

        return {
            "name": self.name,
            "version": "0.1.0",
            "description": f"Auto-profiled contract for {self.name}",
            "time": time_info,
            "grain": grain,
            "metrics": metrics,
            "dimensions": dims,
            "_review_comments": list(self._review_comments),
        }

    def _guess_time_column(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """Detect the time column using keyword matching and parsing."""
        time_keywords = ["date", "period", "time", "timestamp", "day", "month", "year"]
        for col in df.columns:
            if any(k in col.lower() for k in time_keywords):
                try:
                    parsed = pd.to_datetime(df[col].iloc[:10])
                    # Infer frequency from name or data
                    if "period" in col.lower() or "month" in col.lower():
                        freq = "monthly"
                        fmt = "%Y-%m"
                    elif "year" in col.lower():
                        freq = "yearly"
                        fmt = "%Y"
                    else:
                        freq = "daily"
                        fmt = "%Y-%m-%d"
                    return {"column": col, "frequency": freq, "format": fmt}
                except Exception:
                    continue

        # No time column found
        self._review_comments.append(
            "# REVIEW: No time column detected. Add a 'time' section manually if time-series analysis is needed."
        )
        return None

    def _infer_metric_type(self, col: str, series: pd.Series) -> str:
        """Infer whether a metric is additive or non_additive."""
        col_lower = col.lower()

        # Ratio-like keywords
        if any(kw in col_lower for kw in _RATIO_KEYWORDS):
            return "non_additive"

        # Values between 0 and 1 (or 0 and 100 for percentages) are likely ratios
        if series.min() >= 0 and series.max() <= 1.0:
            return "non_additive"
        if series.min() >= 0 and series.max() <= 100.0 and "pct" in col_lower:
            return "non_additive"

        return "additive"

    def _infer_metric_format(self, col: str, series: pd.Series) -> str:
        """Infer the display format for a metric."""
        col_lower = col.lower()

        if any(kw in col_lower for kw in ("amount", "revenue", "cost", "price", "dollar", "usd")):
            return "currency"
        if any(kw in col_lower for kw in ("pct", "percent", "rate", "ratio")):
            return "percent"
        if pd.api.types.is_integer_dtype(series) or (pd.api.types.is_float_dtype(series) and (series == series.astype(int)).all()):
            return "integer"
        return "float"

    def _infer_optimization(self, col: str) -> Tuple[str, bool]:
        """
        Infer optimization direction. Returns (direction, is_certain).
        
        If uncertain, returns ("maximize", False) and adds a REVIEW comment.
        """
        col_lower = col.lower()
        for kw in _MINIMIZE_KEYWORDS:
            if kw in col_lower:
                return "minimize", True
        for kw in _MAXIMIZE_KEYWORDS:
            if kw in col_lower:
                return "maximize", True
        # Ambiguous
        return "maximize", False

    def _guess_metrics(self, df: pd.DataFrame, exclude: List[str]) -> List[Dict[str, Any]]:
        """Detect metric columns (numeric with high cardinality or float type)."""
        metrics = []
        for col in df.columns:
            if col in exclude:
                continue
            if pd.api.types.is_numeric_dtype(df[col]):
                series = df[col]
                # If high cardinality or float, likely a metric
                if series.nunique() > 20 or pd.api.types.is_float_dtype(series):
                    m_type = self._infer_metric_type(col, series)
                    m_format = self._infer_metric_format(col, series)
                    opt_dir, opt_certain = self._infer_optimization(col)

                    metric = {
                        "name": col,
                        "column": col,
                        "type": m_type,
                        "format": m_format,
                        "optimization": opt_dir,
                    }
                    metrics.append(metric)

                    if not opt_certain:
                        self._review_comments.append(
                            f"# REVIEW: Optimization direction for metric '{col}' defaulted to "
                            f"'{opt_dir}'. Verify this is correct."
                        )
        return metrics

    def _guess_dimensions(self, df: pd.DataFrame, exclude: List[str]) -> List[Dict[str, Any]]:
        """Detect dimension columns (categorical or low-cardinality numeric)."""
        dims = []
        for col in df.columns:
            if col in exclude:
                continue
            # Categorical or low-cardinality numeric
            if not pd.api.types.is_numeric_dtype(df[col]) or df[col].nunique() < 50:
                role = "primary" if len(dims) == 0 else "secondary"
                dims.append({"name": col, "column": col, "role": role})
        return dims

    def _guess_grain(
        self,
        df: pd.DataFrame,
        time_info: Optional[Dict],
        dims: List[Dict],
    ) -> Dict[str, Any]:
        """
        Guess the grain: the minimal set of columns that produces unique rows.
        
        Starts with the time column, then adds dimensions one by one (up to 3).
        """
        cols: List[str] = []
        if time_info:
            cols.append(time_info["column"])

        # Add dimensions until unique or max 3
        for d in dims[:3]:
            cols.append(d["column"])
            if not df.duplicated(subset=cols).any():
                break

        # Check if grain is still ambiguous
        if df.duplicated(subset=cols).any():
            self._review_comments.append(
                f"# REVIEW: Inferred grain columns {cols} do not produce unique rows. "
                "Please specify the correct grain manually."
            )

        return {"columns": cols}

    def generate_contract_draft(self, df: pd.DataFrame) -> str:
        """
        Generate a YAML string for the draft DatasetContract.

        The output includes '# REVIEW' comments on uncertain inferences
        as required by FR-010.

        Args:
            df: The DataFrame to profile.

        Returns:
            YAML string that can be saved and edited by a human.
        """
        profile = self.profile_dataframe(df)

        # Build contract-compatible dict
        contract_dict = {
            "name": profile["name"],
            "version": profile["version"],
            "description": profile.get("description", ""),
        }

        if profile["time"]:
            contract_dict["time"] = profile["time"]
        else:
            contract_dict["time"] = {
                "column": "UNKNOWN",
                "frequency": "daily",
                "format": "%Y-%m-%d",
            }

        contract_dict["grain"] = profile["grain"]
        contract_dict["metrics"] = profile["metrics"]
        contract_dict["dimensions"] = profile["dimensions"]

        yaml_str = yaml.dump(contract_dict, sort_keys=False, default_flow_style=False)

        # Append REVIEW comments as a block at the end
        review_comments = profile.get("_review_comments", [])
        if review_comments:
            yaml_str += "\n# === REVIEW ITEMS ===\n"
            for comment in review_comments:
                yaml_str += f"{comment}\n"

        return yaml_str

    def profile(self, df: pd.DataFrame) -> str:
        """
        Public API (T082): profile a DataFrame and return the draft YAML.

        This is the main entry point matching spec US3:
        'Given any pandas DataFrame, generate a draft DatasetContract YAML.'
        """
        return self.generate_contract_draft(df)
