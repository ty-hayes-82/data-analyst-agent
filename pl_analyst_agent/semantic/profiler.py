import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
import yaml
from .models import DatasetContract, MetricDefinition, DimensionDefinition, TimeConfig, GrainConfig

class DatasetProfiler:
    """Analyzes a DataFrame to suggest a DatasetContract draft."""

    def __init__(self, name: str = "Draft Dataset"):
        self.name = name

    def profile_dataframe(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analyzes columns and types to guess contract components."""
        
        time_col = self._guess_time_column(df)
        metrics = self._guess_metrics(df, exclude=[time_col] if time_col else [])
        dims = self._guess_dimensions(df, exclude=[time_col] + [m['column'] for m in metrics])
        grain = self._guess_grain(df, time_col, dims)

        return {
            "name": self.name,
            "version": "0.1.0",
            "time": time_col,
            "grain": grain,
            "metrics": metrics,
            "dimensions": dims
        }

    def _guess_time_column(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        # Look for 'date', 'period', 'time', 'timestamp'
        time_keywords = ['date', 'period', 'time', 'timestamp', 'day', 'month', 'year']
        for col in df.columns:
            if any(k in col.lower() for k in time_keywords):
                # Try to parse
                try:
                    pd.to_datetime(df[col].iloc[:10])
                    return {
                        "column": col,
                        "frequency": "monthly" if "period" in col.lower() else "daily",
                        "format": "%Y-%m-%d"
                    }
                except Exception:
                    continue
        return None

    def _guess_metrics(self, df: pd.DataFrame, exclude: List[str]) -> List[Dict[str, Any]]:
        metrics = []
        for col in df.columns:
            if col in exclude:
                continue
            if pd.api.types.is_numeric_dtype(df[col]):
                # If high cardinality or float, likely a metric
                if df[col].nunique() > 20 or pd.api.types.is_float_dtype(df[col]):
                    metrics.append({
                        "name": col,
                        "column": col,
                        "type": "additive",
                        "format": "float",
                        "optimization": "maximize"
                    })
        return metrics

    def _guess_dimensions(self, df: pd.DataFrame, exclude: List[str]) -> List[Dict[str, Any]]:
        dims = []
        for col in df.columns:
            if col in exclude:
                continue
            # Categorical or low-cardinality numeric
            if not pd.api.types.is_numeric_dtype(df[col]) or df[col].nunique() < 50:
                dims.append({
                    "name": col,
                    "column": col,
                    "role": "primary"
                })
        return dims

    def _guess_grain(self, df: pd.DataFrame, time_info: Optional[Dict], dims: List[Dict]) -> Dict[str, Any]:
        cols = []
        if time_info:
            cols.append(time_info['column'])
        
        # Add dimensions until we hopefully get a unique grain or max 3
        for d in dims[:3]:
            cols.append(d['column'])
            if not df.duplicated(subset=cols).any():
                break
                
        return {"columns": cols}

    def generate_contract_draft(self, df: pd.DataFrame) -> str:
        """Generates a YAML string for the draft contract."""
        profile = self.profile_dataframe(df)
        
        # Convert to DatasetContract-compatible dict
        contract_dict = {
            "name": profile["name"],
            "version": profile["version"],
            "time": profile["time"] or {"column": "unknown", "frequency": "daily"},
            "grain": profile["grain"],
            "metrics": profile["metrics"],
            "dimensions": profile["dimensions"]
        }
        
        return yaml.dump(contract_dict, sort_keys=False)
