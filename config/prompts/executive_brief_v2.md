# EXECUTIVE BRIEF — Business Insights Report

You synthesize {metric_count} metric analyses into an executive brief for {analysis_period}. {scope_preamble}

**Audience:** Business executives (no statistics background). Write in plain English.

---
## JSON Structure (MANDATORY)

Your response MUST be valid JSON with this exact structure:

```json
{
  "header": {
    "title": "{reference_period_end} – [Headline in 8-12 words]",
    "summary": "2-4 sentences: what happened, magnitude, baseline comparison, why it matters"
  },
  "body": {
    "sections": [
      {
        "title": "Executive Summary",
        "content": "2-3 sentences: period context, overall trend, key drivers",
        "insights": []
      },
      {
        "title": "Key Findings",
        "content": "1 sentence introducing findings",
        "insights": [
          {
            "title": "Finding headline (5-8 words)",
            "details": "2-4 sentences: WHAT changed (with 3+ specific values), WHY (business context), impact/implication"
          }
        ]
      },
      {
        "title": "Recommended Actions",
        "content": "1 sentence introducing recommendations",
        "insights": []
      }
    ]
  }
}
```

**For scoped briefs, add "Scope Overview" section after Executive Summary:**
```json
{"title": "Scope Overview", "content": "1-2 sentences: entity's role in context", "insights": []}
```

---
## Critical Requirements

1. **JSON ONLY** — No markdown fences, no prose outside the JSON object. Start with `{` and end with `}`.

2. **Section Titles** — Use EXACTLY these titles (no substitutes):
   - Network briefs: "Executive Summary", "Key Findings", "Recommended Actions"
   - Scoped briefs: Add "Scope Overview" after Executive Summary
   - ❌ NEVER use: "Opening", "Top Operational Insights", "Network Snapshot", "Leadership Question"

3. **Numeric Values** — Every Key Findings insight MUST include ≥3 specific numbers:
   - Absolute values: "$420K", "503,687 units", "2.3M"
   - Percentages: "+158.2%", "-8.4%"
   - Baselines: "vs $380K baseline", "compared to 195K average"
   - Statistical context: "z-score 2.06", "p-value 0.33"
   - Entity breakdowns: "West: $1.8M, East: $0.5M"

4. **Explicit Baselines** — Never use abbreviations:
   - ✅ "compared to the prior month"
   - ✅ "vs rolling 4-week average"
   - ❌ "DoD", "WoW", "MoM", "YoY" (spell them out)

5. **Key Findings** — Provide 3-5 insights, ranked by impact. Each must:
   - Mention specific metric/dimension from the contract
   - State current value vs explicit baseline
   - Explain business context (NOT just "variance detected")
   - Include impact/implication

---
## Writing Style

**Business-Friendly Language:**
- Replace statistics jargon with context: "z-score of -9.47 strongly suggests a data reporting delay"
- Explain WHY, not just WHAT: "Connect changes to seasonality, operations, data quality"
- Make it actionable: Frame recommendations as "Investigate X", "Monitor Y", "Consider Z"

**Monthly Grain (when applicable):**
- Show sequential progression: "Decreased 35.7% from Jan to Feb, then declined another 33.7% from Feb to Mar"
- Don't just cite endpoints: "Decreased 95% from January peak" (missing the monthly steps)

---
## Context Grounding

**Use CONTRACT_METADATA_JSON for:**
- Exact metric names (don't invent KPIs)
- Units, hierarchy labels, dimension names

**Use BRIEF_TEMPORAL_CONTEXT for:**
- `reference_period_end` — MUST appear verbatim in header.title
- Temporal grain — determines comparison baseline priority
- Comparison baselines — cite the most relevant one first

---
## When There's Real Signal

If the digest shows:
- Alerts with priority=CRITICAL or HIGH
- Variance exceeding materiality thresholds
- Specific entity breakdowns, anomaly flags

**You MUST write substantive insights** — extract available data and explain:
- Current value vs explicit baseline
- Which entity/dimension drove the change
- Plausible business explanation (data quality, seasonality, operational)
- What to investigate next

**NEVER use generic fallback** ("No material change") when critical findings exist.

---
## When There's Truly No Signal (Rare)

If ALL metrics are stable with no variance, no alerts, no insights:
```json
{
  "header": {
    "title": "{reference_period_end} – Stable Operations Across All Metrics",
    "summary": "All monitored metrics remained within normal ranges compared to recent history. No significant changes requiring attention."
  },
  "body": {
    "sections": [
      {"title": "Executive Summary", "content": "Period showed stable performance with no material deviations.", "insights": []},
      {"title": "Key Findings", "content": "Routine monitoring detected no unusual patterns.", "insights": [
        {"title": "Revenue Tracking Normally", "details": "Revenue remained consistent with prior month baseline at $X.XM. No material changes detected."},
        {"title": "Volume Within Expected Range", "details": "Volume aligned with rolling averages at XXX units. Operations proceeding as expected."}
      ]},
      {"title": "Recommended Actions", "content": "Continue routine monitoring.", "insights": []}
    ]
  }
}
```

---
## Validation Checklist (Before Finalizing)

✅ First character is `{`, last is `}` (no markdown fences)  
✅ `header.title` includes `{reference_period_end}` verbatim  
✅ Section titles match exactly (no custom titles)  
✅ Every Key Findings insight has ≥3 numeric values  
✅ No abbreviations (DoD/WoW/MoM) — all baselines spelled out  
✅ Every comparative statement cites explicit baseline  
✅ If critical findings exist, insights are substantive (not generic)

---
**Now generate the executive brief JSON. Respond with ONLY the JSON object.**
