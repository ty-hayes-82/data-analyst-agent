# Validation Datapoints Summary

## Quick Checks
- Total rows: 258,624
- Weekly: 210,240 | Monthly: 48,384
- Total trade value: $566,799,852,430.89
- Anomaly rows: 294

## YoY Variance (2024 vs 2023, weekly grain)
- Total: 1.24% (expected positive ~3.5% annual growth)
- Imports: 1.27%
- Exports: 1.19%

## Region Ranking (by absolute variance contribution)
- West: $164,852,281 (1.2%)
- South: $140,193,515 (1.2%)
- Northeast: $138,056,263 (1.5%)
- Midwest: $112,934,748 (1.1%)

## Anomaly Scenarios (6 embedded, 12 grain-specific entries)
- A1 (monthly): volume_drop negative, high severity, 2 rows, deviation -40.25%
- A1 (weekly): volume_drop negative, high severity, 9 rows, deviation -44.42%
- B1 (monthly): surge positive, high severity, 6 rows, deviation 48.26%
- B1 (weekly): surge positive, high severity, 26 rows, deviation 48.79%
- C1 (monthly): weather_disruption negative, medium severity, 16 rows, deviation 0.8%
- C1 (weekly): weather_disruption negative, medium severity, 56 rows, deviation -8.3%
- D1 (monthly): rebound positive, medium severity, 8 rows, deviation 28.8%
- D1 (weekly): rebound positive, medium severity, 36 rows, deviation 26.97%
- E1 (monthly): shutdown negative, high severity, 9 rows, deviation -41.34%
- E1 (weekly): shutdown negative, high severity, 30 rows, deviation -44.53%
- F1 (monthly): demand_shift positive, medium severity, 18 rows, deviation 45.55%
- F1 (weekly): demand_shift positive, medium severity, 78 rows, deviation 46.85%

## Seasonal Pattern (monthly grain)
- Peak month: 3
- Trough month: 10
- Amplitude: 20.15%

## Test Fixtures (in data/validation/)
- fixture_a_lax_imports_weekly.csv — 4,380 rows (contains A1 anomaly: semiconductor tariff shock)
- fixture_b_hou_exports_monthly.csv — 1,008 rows (contains B1 anomaly: energy export surge)
- fixture_c_minimal_lax_8542.csv — 365 rows (single HS4 series, ultra-fast unit tests)
- validation_datapoints.json — full pre-computed expected values

## How Agents Should Use This
1. **Unit tests**: Load fixture_c (365 rows), run sub-agent logic, compare against validation_datapoints.json
2. **Integration tests**: Load fixture_a or fixture_b, run pipeline segment, verify anomaly detection
3. **E2E tests**: Run full pipeline on fixture_a, verify executive brief mentions A1 scenario
4. **Regression**: After any fix, re-run with fixture_c to ensure no regressions
