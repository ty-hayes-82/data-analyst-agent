"""
Test data loader for Data Analyst Agent testing.

Loads real test data from the PL-067-REVENUE-ONLY.csv file
and provides utilities for working with it.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any


class TestDataLoader:
    # Prevent pytest from collecting this as a test class
    __test__ = False
    """Loads and manages test data for Data Analyst Agent tests."""

    def __init__(self):
        """Initialize the test data loader."""
        self.project_root = Path(__file__).parent.parent.parent
        self.data_dir = self.project_root / "data"
        self.test_csv_path = self.data_dir / "PL-067-REVENUE-ONLY.csv"

    def load_pl_067_csv(self) -> pd.DataFrame:
        """
        Load the PL-067 test data CSV file.

        Returns:
            DataFrame with P&L test data

        Raises:
            FileNotFoundError: If test data file doesn't exist
        """
        if not self.test_csv_path.exists():
            raise FileNotFoundError(
                f"Test data file not found: {self.test_csv_path}"
            )

        df = pd.read_csv(self.test_csv_path)

        # Clean column names (remove BOM if present)
        df.columns = df.columns.str.replace('\ufeff', '')

        return df

    def get_pl_067_csv_string(self) -> str:
        """
        Load the PL-067 test data as a CSV string.

        Returns:
            CSV string with test data
        """
        df = self.load_pl_067_csv()
        return df.to_csv(index=False)

    def convert_to_time_series_format(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert wide-format P&L data to time-series format.

        Transforms columns like "2024 - 07", "2024 - 08" into rows
        with period, gl_account, and amount columns.

        Args:
            df: Wide-format DataFrame from CSV

        Returns:
            Long-format DataFrame with period, gl_account, amount columns
        """
        # Identify period columns (format: "YYYY - MM")
        period_cols = [col for col in df.columns if ' - ' in col]

        # ID columns
        id_cols = ['DIV', 'LOB', 'GL_CC', 'Account Nbr',
                   'level_1', 'level_2', 'level_3', 'level_4', 'CTDESC']

        # Melt the DataFrame
        df_melted = pd.melt(
            df,
            id_vars=id_cols,
            value_vars=period_cols,
            var_name='period',
            value_name='amount'
        )

        # Clean period format: "2024 - 07" -> "2024-07"
        df_melted['period'] = df_melted['period'].str.replace(' - ', '-')

        # Clean amount column (remove commas, convert to float)
        df_melted['amount'] = df_melted['amount'].astype(str).str.replace(',', '')
        df_melted['amount'] = pd.to_numeric(df_melted['amount'], errors='coerce')

        # Rename Account Nbr to gl_account for consistency
        df_melted['gl_account'] = df_melted['Account Nbr']

        # Add cost_center
        df_melted['dimension_value'] = df_melted['GL_CC'].astype(str)

        # Add canonical_category (use level_1)
        df_melted['canonical_category'] = df_melted['level_1']

        # Select final columns
        result = df_melted[[
            'period',
            'gl_account',
            'amount',
            'dimension_value',
            'canonical_category',
            'level_1',
            'level_2',
            'level_3',
            'level_4',
            'CTDESC'
        ]].copy()

        # Remove rows with null amounts
        result = result.dropna(subset=['amount'])

        return result

    def get_time_series_csv_string(self) -> str:
        """
        Get test data in time-series format as CSV string.

        Returns:
            CSV string with period, gl_account, amount format
        """
        df = self.load_pl_067_csv()
        df_ts = self.convert_to_time_series_format(df)
        return df_ts.to_csv(index=False)

    def get_mock_ops_metrics(self) -> pd.DataFrame:
        """
        Generate mock operational metrics matching the P&L periods.

        Since PL-067-REVENUE-ONLY.csv doesn't have ops metrics,
        we generate synthetic ones for testing.

        Returns:
            DataFrame with period, miles, stops, loads, cost_center
        """
        df = self.load_pl_067_csv()

        # Get unique periods
        period_cols = [col for col in df.columns if ' - ' in col]
        periods = [col.replace(' - ', '-') for col in period_cols]

        # Generate mock metrics for each period
        data = []
        for period in periods:
            # Use consistent random seed based on period for reproducibility
            seed = int(period.replace('-', ''))
            np.random.seed(seed)

            data.append({
                'period': period,
                'miles': float(np.random.randint(80000, 120000)),
                'stops': float(np.random.randint(2000, 4000)),
                'loads': float(np.random.randint(1500, 3500)),
                'dimension_value': '067'
            })

        return pd.DataFrame(data)

    def get_mock_ops_metrics_csv(self) -> str:
        """
        Get mock operational metrics as CSV string.

        Returns:
            CSV string with ops metrics
        """
        df = self.get_mock_ops_metrics()
        return df.to_csv(index=False)

    def get_validated_pl_data_csv(self) -> str:
        """
        Get validated P&L data with ops metrics joined.

        This simulates the output of the Data Validation Agent.

        Returns:
            CSV string with validated data
        """
        pl_df = self.load_pl_067_csv()
        pl_ts = self.convert_to_time_series_format(pl_df)
        ops_df = self.get_mock_ops_metrics()

        # Join
        merged = pd.merge(
            pl_ts,
            ops_df[['period', 'miles', 'stops', 'loads']],
            on='period',
            how='left'
        )

        return merged.to_csv(index=False)


# Singleton instance
_test_data_loader = TestDataLoader()


# Convenience functions
def load_test_pl_data() -> pd.DataFrame:
    """Load test P&L data as DataFrame."""
    return _test_data_loader.load_pl_067_csv()


def load_test_pl_csv() -> str:
    """Load test P&L data as CSV string."""
    return _test_data_loader.get_pl_067_csv_string()


def load_test_time_series_df() -> pd.DataFrame:
    """Load test data in time-series format as DataFrame."""
    df = _test_data_loader.load_pl_067_csv()
    return _test_data_loader.convert_to_time_series_format(df)


def load_test_time_series_csv() -> str:
    """Load test data in time-series format as CSV string."""
    return _test_data_loader.get_time_series_csv_string()


def load_test_ops_metrics_df() -> pd.DataFrame:
    """Load mock ops metrics as DataFrame."""
    return _test_data_loader.get_mock_ops_metrics()


def load_test_ops_metrics_csv() -> str:
    """Load mock ops metrics as CSV string."""
    return _test_data_loader.get_mock_ops_metrics_csv()


def load_validated_test_data_csv() -> str:
    """Load validated test data (P&L + ops metrics) as CSV string."""
    return _test_data_loader.get_validated_pl_data_csv()
