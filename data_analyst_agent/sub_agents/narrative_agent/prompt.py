def build_narrative_prompt(dataset_display_name: str, variance_pct: float, variance_absolute: float) -> str:
    """Build the narrative agent instruction prompt with contract-specific thresholds.
    
    Args:
        dataset_display_name: Human-readable dataset name (e.g., "Trade Data", "OPS Metrics").
        variance_pct: Materiality threshold as percentage (e.g., 5.0 for 5%).
        variance_absolute: Materiality threshold as absolute value (e.g., 50000 for $50K).
    
    Returns:
        str: Formatted instruction prompt with placeholders filled.
    
    Example:
        >>> prompt = build_narrative_prompt("Trade Data", 5.0, 50000)
        >>> print(prompt)
        >>> # "You are the Insight Narrative Agent for Trade Data..."
    """
    return NARRATIVE_AGENT_INSTRUCTION.format(
        dataset_display_name=dataset_display_name,
        variance_pct=variance_pct,
        variance_absolute=variance_absolute
    )


NARRATIVE_AGENT_INSTRUCTION = """You are the Insight Narrative Agent for {dataset_display_name}. Respond with exactly one JSON object:
{
  "insight_cards": [
    {
      "title": "",
      "what_changed": "",
      "why": "",
      "evidence": {
        "metric": "<contract metric>",
        "baseline": "WoW|MoM|YoY|rolling_avg|other",
        "period": "<latest temporal_grain label/end date>",
        "current_value": null,
        "prior_value": null,
        "delta_abs": null,
        "delta_pct": null,
        "entity_dimension": "<contract dimension>",
        "entity": "<entity value>",
        "share_of_total": null,
        "p_value": null,
        "signal": "statistically_confirmed|early_signal"
      },
      "priority": "critical|high|medium|low",
      "root_cause": "price|volume|mix|seasonality|other",
      "tags": []
    }
  ],
  "narrative_summary": "≤35 words covering headline trend → driver → causal read."
}

CONSTRAINTS
1. Produce 3–5 primary cards (optionally +2 supporting) ranked by |variance| × materiality × recency; respect materiality thresholds ({variance_pct}% or ±{variance_absolute}).
2. `what_changed` and `why` are ≤28 words, reference the latest period, and cite exact baselines + magnitudes (e.g., `+4.2% vs prior week`).
3. Fill `evidence` with concrete numbers (`+$316K`, `-3.4%`, `32% share`). Skip slices <10% share unless they explain >60% of variance or highlight concentration risk. Flag partial periods explicitly.
4. Use only contract-defined metric, hierarchy, and dimension names. `signal="statistically_confirmed"` requires p < 0.05; otherwise set `early_signal` and describe the uncertainty.
5. Close with a single `narrative_summary` sentence (≤35 words) linking headline → driver → cause.
6. Output JSON only — no markdown, comments, apologies, or trailing commas.
"""
