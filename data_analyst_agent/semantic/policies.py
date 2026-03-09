import pandas as pd
from typing import Any, List, Dict, Union, Optional
from .models import DatasetContract

class PolicyEngine:
    """
    Evaluates business policies defined in a DatasetContract against data.
    """
    
    def __init__(self, contract: DatasetContract):
        self.contract = contract
        self.policies = contract.policies or {}

    def get_policy(self, key: str) -> Any:
        """Retrieves a policy by its top-level key."""
        return self.policies.get(key)

    def apply_sign_correction(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Applies sign correction policy to a DataFrame.
        Expected policy format (under policies OR presentation):
        sign_correction:
          - column: "gl_account"
            starts_with: "3"
            multiplier: -1

        A ``sign_flipped`` boolean column is always added, indicating whether
        each row had its sign corrected.
        """
        df_copy = df.copy()
        # Initialise tracking column
        df_copy["sign_flipped"] = False

        # Try policies first, then presentation
        policy = self.get_policy("sign_correction")
        if not policy and hasattr(self.contract, 'presentation'):
            policy = self.contract.presentation.get("sign_correction")

        if not policy:
            return df_copy

        # Ensure policy is a list
        if not isinstance(policy, list):
            policy = [policy]

        for rule in policy:
            col = rule.get("column")
            if col not in df_copy.columns:
                continue

            multiplier = rule.get("multiplier", 1)
            if multiplier == 1:
                continue

            mask = pd.Series(False, index=df_copy.index)

            # Match by 'starts_with'
            starts_with = rule.get("starts_with")
            if starts_with:
                if isinstance(starts_with, str):
                    starts_with = [starts_with]
                for prefix in starts_with:
                    mask |= df_copy[col].astype(str).str.startswith(prefix)

            # Match by 'values'
            values = rule.get("values")
            if values:
                if isinstance(values, (str, int, float)):
                    values = [values]
                mask |= df_copy[col].isin(values)

            # Apply multiplier to all numeric columns (or specific target metric)
            if mask.any():
                # If target_column is specified in rule, use it.
                # Otherwise apply to all metrics defined in contract.
                target_col = rule.get("target_column")
                if target_col and target_col in df_copy.columns:
                    df_copy.loc[mask, target_col] *= multiplier
                else:
                    # Apply to all metric columns in contract that exist in df
                    for metric in self.contract.metrics:
                        if metric.column and metric.column in df_copy.columns:
                            df_copy.loc[mask, metric.column] *= multiplier

                # Mark affected rows
                df_copy.loc[mask, "sign_flipped"] = True

        return df_copy

    def evaluate_item_classification(self, value: Any) -> Optional[str]:
        """
        Classifies an item based on the item_classification policy.
        Example:
        policies:
          item_classification:
            revenue: { starts_with: "3" }
        """
        policy = self.get_policy("item_classification")
        if not policy:
            return None
            
        val_str = str(value).strip()
        
        for category, criteria in policy.items():
            starts_with = criteria.get("starts_with")
            if starts_with:
                if isinstance(starts_with, str):
                    if val_str.startswith(starts_with):
                        return category
                elif isinstance(starts_with, list):
                    if any(val_str.startswith(prefix) for prefix in starts_with):
                        return category
                        
            values = criteria.get("values")
            if values:
                if isinstance(values, list):
                    if value in values or val_str in values:
                        return category
                elif value == values or val_str == str(values):
                    return category
                    
        return None
