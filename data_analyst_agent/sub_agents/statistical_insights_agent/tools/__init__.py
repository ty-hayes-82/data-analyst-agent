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

"""Tools for Statistical Insights Agent."""

from .compute_statistical_summary import compute_statistical_summary
from .compute_seasonal_decomposition import compute_seasonal_decomposition
from .detect_change_points import detect_change_points
from .detect_mad_outliers import detect_mad_outliers
from .compute_forecast_baseline import compute_forecast_baseline
from .compute_derived_metrics import compute_derived_metrics
from .compute_new_lost_same_store import compute_new_lost_same_store
from .compute_concentration_analysis import compute_concentration_analysis
from .compute_cross_metric_correlation import compute_cross_metric_correlation
from .compute_lagged_correlation import compute_lagged_correlation
from .compute_variance_decomposition import compute_variance_decomposition
from .compute_outlier_impact import compute_outlier_impact
from .compute_distribution_analysis import compute_distribution_analysis
from .generate_insight_cards import generate_statistical_insight_cards

__all__ = [
    "compute_statistical_summary",
    "compute_seasonal_decomposition",
    "detect_change_points",
    "detect_mad_outliers",
    "compute_forecast_baseline",
    "compute_derived_metrics",
    "compute_new_lost_same_store",
    "compute_concentration_analysis",
    "compute_cross_metric_correlation",
    "compute_lagged_correlation",
    "compute_variance_decomposition",
    "compute_outlier_impact",
    "compute_distribution_analysis",
    "generate_statistical_insight_cards",
]


