"""
Scoring harness for data-analyst-agent pipeline output.

IMMUTABLE - do not modify during autoresearch experiments.

Scores executive brief output on a 0-100 scale:
  Tier 1 (0-50): Deterministic structural checks (no LLM cost)
  Tier 2 (0-50): LLM critic scoring (one cheap LLM call)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Tier 1: Deterministic structural checks (0-50 points)
# ---------------------------------------------------------------------------

STUB_PHRASES = [
    "no ranked signals were extracted",
    "metric outputs may lack hierarchy cards",
    "verify per-metric json includes",
    "re-run after validating data extracts",
    "validate that metric runs produce",
    "without pass 0 signals",
    "no deterministic signals passed",
]

REQUIRED_SECTIONS = [
    "bottom_line",
    "what_moved",
    "trend_status",
    "where_it_came_from",
    "why_it_matters",
    "leadership_focus",
]


def _count_numbers(text: str) -> int:
    """Count numeric values in text (integers, decimals, percentages)."""
    return len(re.findall(r"-?\d[\d,]*\.?\d*%?", text))


def _has_stub_content(text: str) -> bool:
    """Check if text contains known fallback/stub phrases."""
    lower = text.lower()
    return any(phrase in lower for phrase in STUB_PHRASES)


def _collect_all_insight_cards(metric_jsons: List[Dict]) -> List[Dict]:
    """Collect insight cards from all sources: narrative, hierarchical, statistical."""
    cards = []
    for mj in metric_jsons:
        # Narrative insight cards
        nr = mj.get("narrative_results", {})
        cards.extend(nr.get("insight_cards", []))
        # Hierarchical analysis cards (level_0, level_1, level_2, ...)
        ha = mj.get("hierarchical_analysis", {})
        for level_key, level_val in ha.items():
            if isinstance(level_val, dict):
                cards.extend(level_val.get("insight_cards", []))
                cards.extend(level_val.get("cards", []))
    return cards


def tier1_score(brief_json: Dict[str, Any], brief_md: str, metric_jsons: List[Dict]) -> Tuple[float, Dict[str, Any]]:
    """Score brief output on deterministic structural checks.

    Returns (score, details_dict).
    """
    details: Dict[str, Any] = {}
    score = 0.0

    # 1. JSON validity (5 pts)
    hybrid = brief_json.get("hybrid_pass2_flat") or brief_json.get("hybrid_pipeline_output")
    if hybrid and isinstance(hybrid, dict):
        details["json_valid"] = 5
        score += 5
    elif brief_json.get("sections"):
        details["json_valid"] = 3
        score += 3
    else:
        details["json_valid"] = 0

    # 2. Section completeness (8 pts)
    if hybrid:
        present = sum(1 for s in REQUIRED_SECTIONS if s in hybrid)
        section_score = round(8 * present / len(REQUIRED_SECTIONS), 1)
    else:
        sections = brief_json.get("sections", [])
        section_titles = {s.get("title", "").lower().replace(" ", "_") for s in sections}
        present = sum(1 for s in REQUIRED_SECTIONS if any(s in t for t in section_titles))
        section_score = round(8 * present / len(REQUIRED_SECTIONS), 1)
    details["section_completeness"] = section_score
    score += section_score

    # 3. Numeric density (10 pts)
    num_count = _count_numbers(brief_md)
    numeric_score = min(10.0, round(num_count * 0.67, 1))
    details["numeric_density"] = numeric_score
    details["numeric_count"] = num_count
    score += numeric_score

    # 4. Insight card count (7 pts)
    all_cards = _collect_all_insight_cards(metric_jsons)
    total_cards = len(all_cards)
    # Scale: 5+ cards across all metrics/levels = full marks
    # Per-metric average matters more than total
    n_metrics = max(1, len(metric_jsons))
    avg_cards = total_cards / n_metrics
    if avg_cards >= 3:
        card_score = 7
    elif avg_cards >= 1:
        card_score = 4
    elif total_cards >= 1:
        card_score = 2
    else:
        card_score = 0
    details["insight_card_count"] = total_cards
    details["insight_card_score"] = card_score
    score += card_score

    # 5. Evidence grounding (10 pts)
    grounded = 0
    total_checked = 0
    for card in all_cards:
        total_checked += 1
        # Cards may use different field structures:
        # - narrative cards: current_value, delta_pct, entity
        # - hierarchy cards: evidence.current, evidence.variance_pct, title
        evidence = card.get("evidence", {}) if isinstance(card.get("evidence"), dict) else {}
        has_evidence = (
            card.get("current_value") is not None
            or card.get("delta_pct") is not None
            or card.get("entity")
            or evidence.get("current") is not None
            or evidence.get("variance_pct") is not None
            or card.get("title")
        )
        if has_evidence:
            grounded += 1
    if total_checked > 0:
        evidence_score = round(10 * grounded / total_checked, 1)
    else:
        evidence_score = 0
    details["evidence_grounding"] = evidence_score
    score += evidence_score

    # 6. Contract term compliance (5 pts)
    metric_names_found = 0
    metric_names_total = 0
    for mj in metric_jsons:
        name = mj.get("dimension_value", "")
        if name:
            metric_names_total += 1
            if name.lower().replace("_", " ") in brief_md.lower():
                metric_names_found += 1
    if metric_names_total > 0:
        compliance_score = round(5 * metric_names_found / metric_names_total, 1)
    else:
        compliance_score = 2.5
    details["contract_compliance"] = compliance_score
    score += compliance_score

    # 7. No stub content (5 pts)
    if _has_stub_content(brief_md):
        stub_score = 0
    else:
        stub_score = 5
    details["no_stub"] = stub_score
    score += stub_score

    return round(score, 1), details


# ---------------------------------------------------------------------------
# Tier 2: LLM critic scoring (0-50 points)
# ---------------------------------------------------------------------------

CRITIC_PROMPT_PATH = Path(__file__).parent / "critic_prompt.txt"


def tier2_score(brief_md: str, dataset_desc: str, metrics_list: str) -> Tuple[float, Dict[str, Any]]:
    """Score brief using LLM critic. Returns (score, details_dict)."""
    prompt_template = CRITIC_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        brief_text=brief_md,
        dataset_description=dataset_desc,
        metrics_list=metrics_list,
    )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        text = response.text.strip()
        scores = json.loads(text)

        total = 0
        details: Dict[str, Any] = {}
        for dim in ["actionability", "causal_depth", "data_specificity", "narrative_coherence", "completeness"]:
            val = min(10, max(0, int(scores.get(dim, 0))))
            details[dim] = val
            total += val
        return float(total), details

    except Exception as exc:
        print(f"[evaluate] Tier 2 LLM critic failed: {exc}")
        return 0.0, {"error": str(exc)}


# ---------------------------------------------------------------------------
# Full scoring
# ---------------------------------------------------------------------------

def score_run(output_dir: str, dataset_config: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    """Score a complete pipeline run."""
    output_path = Path(output_dir)

    brief_json_path = output_path / "deliverables" / "brief.json"
    brief_md_path = output_path / "deliverables" / "brief.md"

    brief_json = {}
    brief_md = ""

    if brief_json_path.exists():
        brief_json = json.loads(brief_json_path.read_text(encoding="utf-8"))
    if brief_md_path.exists():
        brief_md = brief_md_path.read_text(encoding="utf-8")

    metrics_dir = output_path / "metrics"
    metric_jsons = []
    if metrics_dir.exists():
        for f in sorted(metrics_dir.glob("metric_*.json")):
            metric_jsons.append(json.loads(f.read_text(encoding="utf-8")))

    t1_score, t1_details = tier1_score(brief_json, brief_md, metric_jsons)
    t2_score, t2_details = tier2_score(
        brief_md,
        dataset_config.get("description", ""),
        dataset_config.get("metrics", ""),
    )

    total = round(t1_score + t2_score, 1)
    details = {
        "bqs_total": total,
        "tier1_score": t1_score,
        "tier2_score": t2_score,
        "tier1_details": t1_details,
        "tier2_details": t2_details,
    }
    return total, details


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python evaluate.py <output_dir> [dataset_name]")
        sys.exit(1)

    output_dir = sys.argv[1]
    dataset_name = sys.argv[2] if len(sys.argv) > 2 else "unknown"

    sys.path.insert(0, str(Path(__file__).parent))
    from datasets import EVAL_DATASETS, HOLDOUT_DATASETS
    all_ds = EVAL_DATASETS + HOLDOUT_DATASETS
    ds_config = next((d for d in all_ds if d["name"] == dataset_name), {"name": dataset_name, "metrics": "", "description": ""})

    total, details = score_run(output_dir, ds_config)
    print(json.dumps(details, indent=2))
    print(f"\nBQS Total: {total}/100")
