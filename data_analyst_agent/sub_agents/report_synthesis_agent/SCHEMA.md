# Report Synthesis Agent - Canonical Input Schemas

This document describes the expected JSON formats for `generate_markdown_report` tool parameters.
The tool normalizes multiple formats; these examples define the **canonical** structure for consistency.

## hierarchical_results

Preferred format: object with `level_0`, `level_1`, optionally `level_2` keys.

```json
{
  "level_0": {
    "insight_cards": [
      {
        "title": "Level 0 Variance Driver: Total",
        "what_changed": "Variance of +6,090.00 (+0.0%)",
        "why": "Aggregated favorable impact at the Total level.",
        "evidence": {
          "variance_dollar": 6090.0,
          "variance_pct": 0.0,
          "current": 6090.0,
          "prior": 0.0,
          "share_of_total": 1.0
        },
        "priority": "high",
        "impact_score": 0.3
      }
    ],
    "total_variance_dollar": 6090.0,
    "level_name": "Total"
  },
  "level_1": {
    "insight_cards": [
      {
        "title": "Level 1 Variance Driver: East",
        "what_changed": "Variance of +2,557.00 (+0.0%)",
        "why": "Aggregated favorable impact at the Region level.",
        "evidence": { "variance_dollar": 2557.0, "share_of_total": 0.4199 },
        "priority": "low"
      }
    ],
    "total_variance_dollar": 6090.0,
    "level_name": "Region"
  }
}
```

Alternative (also supported): `level_N` as array of insight cards. The tool normalizes both.

## narrative_results

```json
{
  "insight_cards": [
    {
      "title": "Rapid Volume Expansion at Richmond Terminal",
      "what_changed": "Richmond volume surged to 288 trucks...",
      "why": "Richmond is experiencing a sustained growth trend...",
      "evidence": { "current_value": 288.0, "average_value": 204.89, "slope_3mo": 35.0 },
      "priority": "critical",
      "root_cause": "volume",
      "tags": ["terminal_performance", "growth_trend", "anomaly"]
    }
  ],
  "narrative_summary": "Total Truck Count reached a period peak..."
}
```

## statistical_summary (slim subset)

```json
{
  "summary_stats": {
    "total_items": 37,
    "total_periods": 27,
    "period_range": "2025-08-16 to 2026-02-14",
    "highest_total_month": { "period": "2026-02-14", "total": 6090.0 },
    "lowest_total_month": { "period": "2026-01-03", "total": 5719.0 },
    "total_anomalies_detected": 20
  },
  "top_drivers": [
    { "item": "Richmond", "avg": 204.89, "slope_3mo": 35.0, "share_of_total": 0.0351, "anomaly_latest": true }
  ],
  "anomalies": [
    { "period": "2026-02-14", "item": "Pueblo", "value": 1.0, "z_score": 5.1 }
  ]
}
```

## Required parameters

- **hierarchical_results**: JSON string (required)
- **analysis_target**: string (required)
- **analysis_period**: string (optional)
- **statistical_summary**: JSON string (optional)
- **narrative_results**: JSON string (optional)
- **target_label**: string (optional)
