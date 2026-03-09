from typing import List, Any, Optional, Tuple

def resolve_effective_latest_period(
    periods: List[Any], 
    lag_periods: int = 0
) -> Tuple[Any, List[Any]]:
    """
    Given a sorted list of periods and a lag offset, return:
      - effective_current: the period treated as "latest" for analysis
      - lag_window: list of periods in the incomplete lag window
    """
    if not periods:
        return None, []
        
    if lag_periods <= 0:
        return periods[-1], []
        
    if lag_periods >= len(periods):
        # Lag exceeds available data - fall back to latest available but warn
        # (Logging would happen at call site if needed, or we could add it here)
        return periods[-1], []
        
    effective_idx = -(1 + lag_periods)
    effective_current = periods[effective_idx]
    lag_window = periods[effective_idx + 1:]
    
    return effective_current, lag_window

def get_lag_window_periods(periods: List[Any], lag_periods: int) -> List[Any]:
    """Returns only the list of periods in the lag window."""
    _, lag_window = resolve_effective_latest_period(periods, lag_periods)
    return lag_window

def is_period_in_lag_window(period: Any, lag_window: List[Any]) -> bool:
    """True if the given period is within the incomplete lag window."""
    return period in lag_window


def get_effective_lag_or_default(contract: Any, metric: Any, default: int = 0) -> int:
    """Safely fetch contract.get_effective_lag(metric), returning an int fallback."""
    try:
        if contract is None:
            return default
        value = contract.get_effective_lag(metric)
        if value is None:
            return default
        return int(value)
    except (AttributeError, TypeError, ValueError):
        return default
