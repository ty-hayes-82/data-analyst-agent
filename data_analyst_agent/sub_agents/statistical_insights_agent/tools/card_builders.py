"""Compatibility layer for the card builder functions.

Historically, all card builders lived in this single file. To keep
imports stable while enabling more focused modules, we now re-export the
public builder helpers from the dedicated modules in
``card_builder_modules``.
"""

from __future__ import annotations

from .card_builder_modules.anomaly_cards import (  # noqa: F401
    _build_anomaly_cards,
    _build_forecast_deviation_cards,
    _build_outlier_impact_cards,
    _build_seasonal_anomaly_cards,
)
from .card_builder_modules.correlation_cards import (  # noqa: F401
    _build_correlation_cards,
    _build_cross_metric_correlation_cards,
)
from .card_builder_modules.portfolio_cards import (  # noqa: F401
    _build_concentration_cards,
    _build_new_lost_same_store_cards,
)
from .card_builder_modules.trend_cards import (  # noqa: F401
    _build_change_point_cards,
    _build_leading_indicator_cards,
    _build_trend_cards,
    _build_volatility_cards,
)
from .card_builder_modules.variance_cards import (  # noqa: F401
    _build_cross_dimension_cards,
    _build_distribution_cards,
    _build_variance_decomposition_cards,
)

__all__ = [
    "_build_anomaly_cards",
    "_build_forecast_deviation_cards",
    "_build_seasonal_anomaly_cards",
    "_build_outlier_impact_cards",
    "_build_trend_cards",
    "_build_volatility_cards",
    "_build_change_point_cards",
    "_build_correlation_cards",
    "_build_cross_metric_correlation_cards",
    "_build_leading_indicator_cards",
    "_build_new_lost_same_store_cards",
    "_build_concentration_cards",
    "_build_variance_decomposition_cards",
    "_build_distribution_cards",
    "_build_cross_dimension_cards",
]
