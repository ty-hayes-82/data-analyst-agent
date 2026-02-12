import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from .models import DatasetContract, QualityReport
from .exceptions import QualityGateError

class DataQualityGate:
    """Validates a DataFrame against a DatasetContract."""

    def __init__(self, contract: DatasetContract):
        self.contract = contract

    def validate(self, df: pd.DataFrame) -> QualityReport:
        """Runs all quality checks and returns a QualityReport."""
        checks = {}
        errors = []
        warnings = []
        
        # 1. Schema Check
        schema_ok, schema_errors = self._check_schema(df)
        checks["schema_validation"] = schema_ok
        errors.extend(schema_errors)
        
        if not schema_ok:
            # Cannot proceed with other checks if schema is broken
            return QualityReport(
                contract_name=self.contract.name,
                is_valid=False,
                checks=checks,
                errors=errors
            )

        # 2. Grain Check
        grain_ok, grain_errors = self._check_grain(df)
        checks["grain_uniqueness"] = grain_ok
        errors.extend(grain_errors)

        # 3. Time Continuity Check
        time_ok, time_warnings = self._check_time_continuity(df)
        checks["time_continuity"] = time_ok
        warnings.extend(time_warnings)

        # 4. Metric Additivity Check (Sample check)
        # For now, we just check if they are numeric
        metrics_ok, metrics_errors = self._check_metrics(df)
        checks["metrics_integrity"] = metrics_ok
        errors.extend(metrics_errors)

        is_valid = len(errors) == 0

        return QualityReport(
            contract_name=self.contract.name,
            is_valid=is_valid,
            checks=checks,
            errors=errors,
            warnings=warnings
        )

    def _check_schema(self, df: pd.DataFrame) -> (bool, List[str]):
        required_cols = set()
        required_cols.add(self.contract.time.column)
        for m in self.contract.metrics:
            required_cols.add(m.column)
        for d in self.contract.dimensions:
            required_cols.add(d.column)
        
        # Resolve grain columns (they could be semantic names or physical names)
        for g in self.contract.grain.columns:
            if g in self.contract._dim_map:
                required_cols.add(self.contract._dim_map[g].column)
            else:
                required_cols.add(g)
            
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            return False, [f"Missing required columns: {missing}"]
        return True, []

    def _check_grain(self, df: pd.DataFrame) -> (bool, List[str]):
        # Resolve grain columns to physical names
        grain_cols = []
        for g in self.contract.grain.columns:
            if g in self.contract._dim_map:
                grain_cols.append(self.contract._dim_map[g].column)
            else:
                grain_cols.append(g)

        duplicates = df.duplicated(subset=grain_cols).sum()
        if duplicates > 0:
            return False, [f"Found {duplicates} duplicate rows for grain {grain_cols}"]
        return True, []

    def _check_time_continuity(self, df: pd.DataFrame) -> (bool, List[str]):
        # Convert to datetime if not already
        time_col = self.contract.time.column
        try:
            temp_time = pd.to_datetime(df[time_col])
        except Exception as e:
            return False, [f"Failed to parse time column '{time_col}': {str(e)}"]

        # Simple continuity check: count unique periods vs expected
        # This is a basic version; in Phase 2/3 we might do frequency-based checks
        return True, [] # Placeholder for more advanced logic

    def _check_metrics(self, df: pd.DataFrame) -> (bool, List[str]):
        errors = []
        for m in self.contract.metrics:
            if not pd.api.types.is_numeric_dtype(df[m.column]):
                errors.append(f"Metric column '{m.column}' is not numeric")
        
        return len(errors) == 0, errors
