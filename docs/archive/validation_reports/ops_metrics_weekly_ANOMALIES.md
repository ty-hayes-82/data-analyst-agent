# Ops Metrics Weekly Validation Dataset - Known Anomalies

**Dataset**: `ops_metrics_weekly_validation.csv`  
**Generated**: 2024-03-18  
**Purpose**: Validation dataset with embedded known anomalies for testing pipeline detection capabilities

## Dataset Structure

- **Time Range**: 2024-01-01 to 2024-03-30 (90 days, daily grain)
- **Dimensions**: 
  - 3 Regions: East, Central, West
  - 2 Divisions per Region (6 total)
  - 2 Business Lines: Dedicated, Regional
  - **Total dimension combinations**: 12
- **Total Rows**: 1,080 (90 days × 12 combinations)
- **Metrics**: ttl_rev_amt, lh_rev_amt, fuel_srchrg_rev_amt, acsrl_rev_amt, ordr_cnt, ordr_miles, truck_count, dh_miles

## Baseline Characteristics

- **Revenue**: ~$120K/day per dimension combo (with ±10% natural noise)
- **Weekend Pattern**: Revenue/orders drop to ~60% on Saturdays and Sundays
- **Natural Variation**: All metrics include realistic noise (±10% standard deviation)
- **Hierarchy Integrity**: Division values designed to roll up to regions correctly

---

## Embedded Anomalies (Ground Truth)

### 1. Revenue Drop Anomaly

**Type**: Revenue gap (volume/miles normal, revenue collapsed)

**Location**:
- **Date Range**: 2024-02-15 to 2024-02-18 (Days 45-48)
- **Dimension**: Region = "East" (all divisions/business lines)
- **Affected Rows**: 16 (4 days × 4 dimension combos under East)

**Behavior**:
- `ttl_rev_amt` drops to **30% of baseline** (~$36K vs ~$120K)
- `lh_rev_amt` drops to **30% of baseline**
- Other metrics (`ordr_cnt`, `ordr_miles`, `truck_count`, `dh_miles`) remain **normal**
- Classic revenue leak: volume is normal but pricing/billing collapsed

**Expected Detection**:
- HierarchyVarianceAgent should flag East region with large negative variance
- StatisticalAnalysisAgent should detect revenue outlier
- NarrativeAgent should identify revenue vs volume mismatch pattern
- **Priority**: HIGH (material revenue impact)

**Business Context**: Simulates billing system error or pricing misconfiguration affecting entire region

---

### 2. Spike in Deadhead Miles

**Type**: Operational inefficiency

**Location**:
- **Date Range**: 2024-03-04 to 2024-03-06 (Days 63-65, Mon-Wed)
- **Dimension**: Division = "East-Northeast" (both business lines)
- **Affected Rows**: 6 (3 days × 2 business lines)

**Behavior**:
- `dh_miles` spikes to **300% of baseline** (~9,000 miles vs ~3,000 miles)
- All other metrics remain **normal**
- Efficiency metric degradation without impacting revenue or volume

**Expected Detection**:
- StatisticalAnalysisAgent should flag deadhead miles spike (3σ above mean)
- NarrativeAgent should highlight operational inefficiency
- Efficiency ratio (dh_miles / ordr_miles) should be flagged
- **Priority**: MEDIUM (cost/efficiency issue, but revenue intact)

**Business Context**: Simulates routing problem, driver shortage, or network imbalance causing excessive empty miles

---

### 3. Sustained Order Volume Drop

**Type**: Business contraction

**Location**:
- **Date Range**: 2024-03-11 to 2024-03-26 (Days 70-85, 16 days)
- **Dimension**: Business Line = "Dedicated" (all regions/divisions)
- **Affected Rows**: 96 (16 days × 6 dimension combos with Dedicated)

**Behavior**:
- `ordr_cnt` drops **40%** (~150 vs ~250)
- `ttl_rev_amt` drops **40%** proportionally
- All revenue components drop proportionally
- **Sustained** over 2+ weeks (not a spike, a step-change)

**Expected Detection**:
- HierarchyVarianceAgent should flag Dedicated business line at all levels
- SeasonalBaselineAgent should detect persistent deviation from baseline
- NarrativeAgent should identify sustained contraction pattern
- **Priority**: HIGH (material business impact, sustained duration)

**Business Context**: Simulates customer loss, contract expiration, or market share decline in Dedicated segment

---

### 4. Fuel Surcharge Anomaly

**Type**: Billing error pattern

**Location**:
- **Date Range**: 2024-01-30 to 2024-02-04 (Days 29-34, 6 days)
- **Dimension**: Region = "West" (all divisions/business lines)
- **Affected Rows**: 24 (6 days × 4 dimension combos under West)

**Behavior**:
- `fuel_srchrg_rev_amt` goes to **$0** (complete drop)
- Other revenue components (`lh_rev_amt`, `acsrl_rev_amt`) remain **normal**
- `ttl_rev_amt` reduced by ~25% (fuel surcharge portion missing)

**Expected Detection**:
- HierarchyVarianceAgent should flag West region revenue gap
- StatisticalAnalysisAgent should detect fuel surcharge component drop
- NarrativeAgent should identify component-specific revenue issue
- **Priority**: MEDIUM-HIGH (revenue impact, but specific component identifiable)

**Business Context**: Simulates billing system error where fuel surcharge calculation fails for region

---

### 5. Weekend Spike Anomaly

**Type**: Seasonal/temporal anomaly

**Location**:
- **Date Range**: 2024-02-24 (Day 54, Saturday)
- **Dimension**: All regions, divisions, business lines
- **Affected Rows**: 12 (1 day × 12 dimension combos)

**Behavior**:
- `ordr_cnt` spikes to **2x normal weekend levels** (~300 vs ~150)
- Should be anomalous because Saturdays typically have **lower** volume
- Revenue and other metrics increase proportionally

**Expected Detection**:
- SeasonalBaselineAgent should flag weekend anomaly (opposite of expected pattern)
- StatisticalAnalysisAgent should detect day-of-week outlier
- NarrativeAgent should highlight unusual weekend activity
- **Priority**: LOW-MEDIUM (positive anomaly, could be special event)

**Business Context**: Simulates emergency freight surge, special event, or backlog clearing on weekend

---

### 6. Truck Count Drop

**Type**: Fleet capacity issue

**Location**:
- **Date Range**: 2024-02-25 to 2024-03-01 (Days 55-60, 6 days)
- **Dimension**: Division = "Central-Midwest" (both business lines)
- **Affected Rows**: 12 (6 days × 2 business lines)

**Behavior**:
- `truck_count` drops **25%** (~60 vs ~80 trucks)
- `ordr_miles` drops **25%** proportionally
- `ordr_cnt` drops **25%** proportionally
- `ttl_rev_amt` drops **25%** proportionally
- **Coherent degradation** across all operational metrics

**Expected Detection**:
- HierarchyVarianceAgent should flag Central-Midwest division
- StatisticalAnalysisAgent should detect correlated metric drops
- NarrativeAgent should identify fleet capacity constraint pattern
- **Priority**: MEDIUM-HIGH (operational constraint limiting revenue)

**Business Context**: Simulates fleet maintenance event, driver shortage, or temporary capacity reduction

---

## Validation Test Cases

### Test 1: Anomaly Detection Coverage
**Objective**: Verify pipeline detects all 6 anomalies  
**Success Criteria**: Each anomaly appears in at least one agent's output (narrative card or alert)

### Test 2: Priority Assignment
**Objective**: Verify alert scoring aligns with expected priorities  
**Success Criteria**:
- Anomalies 1, 3 → HIGH priority
- Anomalies 2, 4, 6 → MEDIUM-HIGH priority
- Anomaly 5 → LOW-MEDIUM priority

### Test 3: Pattern Recognition
**Objective**: Verify narratives correctly characterize anomaly types  
**Success Criteria**:
- Anomaly 1: Revenue vs volume mismatch identified
- Anomaly 2: Efficiency degradation identified
- Anomaly 3: Sustained contraction pattern identified
- Anomaly 4: Component-specific revenue issue identified
- Anomaly 5: Temporal pattern break identified
- Anomaly 6: Correlated operational constraint identified

### Test 4: Hierarchy Drill-Down
**Objective**: Verify anomalies detected at correct hierarchy level  
**Success Criteria**:
- Anomalies 1, 4 detected at Region level
- Anomalies 2, 6 detected at Division level
- Anomaly 3 detected at Business Line level
- Anomaly 5 detected at All-level (temporal)

### Test 5: False Positive Rate
**Objective**: Verify pipeline doesn't flag non-anomalous periods  
**Success Criteria**:
- Days 1-29, 36-44, 49-54, 63-69, 86-90 should have minimal/no alerts
- Weekend patterns (60% reduction) should NOT be flagged as anomalies

---

## Usage Instructions

### Load Dataset
```python
import pandas as pd

df = pd.read_csv('data/validation/ops_metrics_weekly_validation.csv')
print(f"Loaded {len(df)} rows")
print(f"Date range: {df['cal_dt'].min()} to {df['cal_dt'].max()}")
```

### Run Pipeline
```bash
cd /data/data-analyst-agent
ACTIVE_DATASET=ops_metrics_weekly_validation python -m data_analyst_agent
```

### Inspect Anomaly Periods
```python
# Anomaly 1: Revenue Drop (Days 45-48, East)
anomaly1 = df[(df['cal_dt'] >= '2024-02-15') & (df['cal_dt'] <= '2024-02-18') & (df['gl_rgn_nm'] == 'East')]
print(anomaly1[['cal_dt', 'gl_rgn_nm', 'ttl_rev_amt', 'ordr_cnt']].mean())

# Anomaly 2: Deadhead Spike (Days 63-65, East-Northeast)
anomaly2 = df[(df['cal_dt'] >= '2024-03-04') & (df['cal_dt'] <= '2024-03-06') & (df['gl_div_nm'] == 'East-Northeast')]
print(anomaly2[['cal_dt', 'gl_div_nm', 'dh_miles', 'ordr_miles']].mean())
```

### Verify Anomalies Visually
```python
import matplotlib.pyplot as plt

# Plot revenue for East region over time
east_revenue = df[df['gl_rgn_nm'] == 'East'].groupby('cal_dt')['ttl_rev_amt'].sum()
plt.figure(figsize=(12, 4))
plt.plot(east_revenue.index, east_revenue.values)
plt.axvspan('2024-02-15', '2024-02-18', alpha=0.3, color='red', label='Anomaly 1')
plt.title('East Region Revenue - Anomaly 1 Visible')
plt.xlabel('Date')
plt.ylabel('Total Revenue ($)')
plt.legend()
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
```

---

## Notes

- **Random Seed**: Fixed at 42 for reproducibility
- **Baseline Realism**: Revenue/volumes calibrated to realistic trucking operations scale
- **Hierarchy Integrity**: Anomalies respect geographic/business line hierarchy structure
- **No Overlap**: Anomalies are temporally and dimensionally isolated to avoid confounding effects
- **Detection Difficulty**: Varies from obvious (Anomaly 4: fuel surcharge → $0) to subtle (Anomaly 5: weekend spike)

## Regeneration

To regenerate this dataset with different random noise but same anomaly structure:
```bash
cd /data/data-analyst-agent
python scripts/generate_validation_ops_weekly.py
```

Change `np.random.seed(42)` in the script to get different baseline noise patterns.
