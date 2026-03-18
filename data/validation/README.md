# Validation Dataset: Ops Metrics Weekly

## Overview
This directory contains a synthetic validation dataset for testing the Data Analyst Agent pipeline's anomaly detection capabilities.

## Files

### `ops_metrics_weekly_validation.csv` (109 KB)
- **Purpose**: Synthetic trucking operations data with 6 embedded known anomalies
- **Structure**: 1,080 rows (90 days × 12 dimension combinations)
- **Date Range**: 2024-01-01 to 2024-03-30
- **Dimensions**: 3 regions × 6 divisions × 2 business lines
- **Metrics**: 8 metrics (revenue, orders, miles, trucks, deadhead)
- **Random Seed**: 42 (for reproducibility)

### `ops_metrics_weekly_ANOMALIES.md` (10 KB)
- **Purpose**: Ground truth documentation for all embedded anomalies
- **Contents**:
  - Detailed description of each of the 6 anomalies
  - Expected detection behavior per agent
  - Alert priority expectations
  - Validation test cases
  - Usage instructions with code examples

## Quick Start

### 1. Inspect the Dataset
```bash
cd /data/data-analyst-agent
python scripts/validate_ops_weekly.py
```

This will verify:
- ✓ All 6 anomalies are properly embedded
- ✓ Dataset structure matches contract requirements
- ✓ No null values or data quality issues

### 2. Run the Pipeline
```bash
cd /data/data-analyst-agent
ACTIVE_DATASET=ops_metrics_weekly_validation python -m data_analyst_agent
```

### 3. Verify Anomaly Detection
Check the output report to confirm:
- All 6 anomalies are detected
- Priority levels match expectations
- Narrative descriptions are accurate

## Embedded Anomalies Summary

| # | Type | Location | Dates | Expected Priority |
|---|------|----------|-------|------------------|
| 1 | Revenue Drop | East region | Feb 15-18 | HIGH |
| 2 | Deadhead Spike | East-Northeast division | Mar 4-6 | MEDIUM |
| 3 | Order Volume Drop | Dedicated business line | Mar 11-26 | HIGH |
| 4 | Fuel Surcharge Zero | West region | Jan 30 - Feb 4 | MEDIUM-HIGH |
| 5 | Weekend Spike | All dimensions | Feb 24 (Sat) | LOW-MEDIUM |
| 6 | Truck Count Drop | Central-Midwest division | Feb 25 - Mar 1 | MEDIUM-HIGH |

See `ops_metrics_weekly_ANOMALIES.md` for detailed specifications.

## Validation Results

Last validated: 2024-03-18

```
✓ All 12 required columns present
✓ 1,080 rows (90 days × 12 dimension combos)
✓ Date range: 2024-01-01 to 2024-03-30
✓ No null values
✓ All 6 anomalies confirmed present:
  ✓ Anomaly 1: Revenue drops to 27.0% (expected ~30%)
  ✓ Anomaly 2: Deadhead spikes to 3.0x (expected ~3.0x)
  ✓ Anomaly 3: Orders drop to 64.5% (expected ~60%)
  ✓ Anomaly 4: Fuel surcharge = $0 (expected $0)
  ✓ Anomaly 5: Weekend orders 2.1x (expected ~2.0x)
  ✓ Anomaly 6: Trucks drop to 79.5% (expected ~75%)
```

## Regenerating the Dataset

If you need to regenerate with different random noise:

```bash
cd /data/data-analyst-agent
python scripts/generate_validation_ops_weekly.py
```

To change the random seed, edit the script:
```python
np.random.seed(42)  # Change to any integer
```

## Notes

- **Simplified Grain**: This dataset uses a simplified dimension hierarchy (region → division → business line) compared to the full contract which includes cost centers and manager codes
- **Missing Column**: `icc_cst_ctr_cd` is intentionally omitted (not needed for validation testing)
- **Realistic Scale**: Revenue values calibrated to $50K-200K/day per dimension combo (realistic for trucking operations)
- **Weekend Patterns**: Built-in weekend reduction (60% of weekday levels) to simulate realistic operational patterns
- **No Overlap**: Anomalies are temporally and dimensionally isolated to avoid confounding effects

## Success Criteria

**Pass Criteria for Pipeline Validation:**
1. All 6 anomalies appear in narrative cards or alerts
2. High-priority anomalies (1, 3) flagged as material
3. Pattern descriptions match anomaly types (revenue vs volume mismatch, sustained contraction, etc.)
4. Hierarchy drill-down identifies correct dimension level for each anomaly
5. False positive rate is low (non-anomalous periods don't trigger alerts)

## Contact

Questions about this validation dataset? See `ops_metrics_weekly_ANOMALIES.md` for detailed documentation.
