# ADR: Derived metrics and aggregation semantics

## Context

The pipeline:

1. Loads **wide** Hyper (or CSV) rows at a fine grain (e.g. week x region x division x ...).
2. Materializes contract `derived_kpis` with **`df.eval(formula)` per row** (bases are already SQL sums for that grain).
3. Hierarchy / level statistics often computed **`groupby(dimension)[metric].sum()`**.

**Additive** derived metrics (e.g. `total_miles = ld_mi_less_swift_billto + dh_miles`, `xFSR = ttl_rev_amt - fuel_srchrg_rev_amt`): summing row-level derived values equals applying the same linear form to summed bases. **Totals match Tableau.**

**Ratio** derived metrics (e.g. `TRPM = xFSR / total_miles`, `deadhead_pct = 100 * dh / total_miles`): **sum(row ratios) is not equal to ratio(sum numerators, sum denominators).** Summing the derived column breaks network and regional rollups and can produce NaNs / infinities.

## Decision

1. **Classify** `derived_kpis` shapes:
   - `subtract` / `add` only: treat as **structurally additive** for rollups (row `eval` + sum is valid).
   - `denominator` or `divide_by`: treat as **ratio**; rollups must use **aggregate-then-divide**.

2. **Source of truth**: `derived_kpis` in `contract.yaml`. Expand nested KPI references to expressions over **physical (additive) columns only** via `kpi_to_aggregate_ratio_parts()` in `derived_kpi_formula.py`.

3. **Hierarchy level stats**: When `get_ratio_config_for_metric()` returns `numerator_expr` / `denominator_expr` (from contract derived KPIs) or legacy `numerator_metric` / `denominator_metric` (from `ratio_metrics.yaml`), use **`_aggregate_wide_dataframe_exprs`** to:
   - `groupby(level).sum()` over referenced base columns,
   - `eval` numerator and denominator expressions on the grouped frame,
   - apply `multiply` and divide (zero-safe).

4. **Precedence**: Explicit **`ratio_metrics.yaml`** next to the contract overrides contract-derived ratio config for the same metric name.

5. **Temporal labeling**: Tableau loaders that use `week_end` aggregation should set **`time.temporal_grain_override: weekly`** so analysis metadata does not claim `daily` when the extract is weekly-bucketed.

## Consequences

- No need to duplicate ratio definitions in YAML for datasets that already encode them in `derived_kpis`.
- Datasets with unusual ratio logic can still ship **`ratio_metrics.yaml`** for overrides.
- New ratio-shaped KPIs automatically get correct rollups when `derived_kpis` are well-formed.

## Status

Accepted; contract-derived expr aggregation implemented in `level_stats/ratio_metrics.py` and `semantic/ratio_metrics_config.py`.
