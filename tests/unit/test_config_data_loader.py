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
Unit test for config_data_loader to ensure parity with validation_data_loader.
"""

import unittest
import pandas as pd
from data_analyst_agent.tools.validation_data_loader import load_validation_data
from data_analyst_agent.tools.config_data_loader import load_from_config


class TestConfigDataLoaderParity(unittest.TestCase):
    """Ensure config_data_loader matches validation_data_loader exactly."""

    def test_full_load_parity(self):
        """Test full load of validation_ops."""
        # 1. Load via existing loader
        df_old = load_validation_data()
        
        # 2. Load via new config loader
        df_new = load_from_config("validation_ops")
        
        # 3. Assert parity
        self.assertEqual(len(df_old), len(df_new), "Row counts must match")
        self.assertEqual(list(df_old.columns), list(df_new.columns), "Columns must match")
        
        # Ensure values and types match
        pd.testing.assert_frame_equal(df_old, df_new)
        print(f"[TEST] Full load parity confirmed ({len(df_old):,} rows)")

    def test_filtered_load_parity(self):
        """Test filtered load of validation_ops."""
        params = {
            "region_filter": "Central",
            "terminal_filter": "Albuquerque",
            "metric_filter": "Truck Count",
            "exclude_partial_week": True
        }
        
        # 1. Load via existing loader
        df_old = load_validation_data(**params)
        
        # 2. Load via new config loader
        df_new = load_from_config("validation_ops", **params)
        
        # 3. Assert parity
        pd.testing.assert_frame_equal(df_old, df_new)
        print(f"[TEST] Filtered load parity confirmed ({len(df_old):,} rows)")

    def test_multi_metric_parity(self):
        """Test multi-metric list filter."""
        metrics = ["Truck Count", "Rev/Trk/Wk"]
        
        # 1. Load via existing loader
        df_old = load_validation_data(metric_filter=metrics)
        
        # 2. Load via new config loader
        df_new = load_from_config("validation_ops", metric_filter=metrics)
        
        # 3. Assert parity
        pd.testing.assert_frame_equal(df_old, df_new)
        print(f"[TEST] Multi-metric parity confirmed ({len(df_old):,} rows)")


if __name__ == "__main__":
    unittest.main()
