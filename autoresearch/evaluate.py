"""
Scoring harness for data-analyst-agent pipeline output.

IMMUTABLE - do not modify during autoresearch experiments.

Scores executive brief output on a 0-100 scale:
  Tier 0 (0-15): Data accuracy vs ground truth (no LLM cost)
  Tier 1 (0-40): Deterministic structural checks (no LLM cost)
  Tier 2 (0-45): LLM critic scoring (one cheap LLM call)
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Tier 0: Data accuracy vs ground truth (0-15 points)
# ---------------------------------------------------------------------------

def _find_ground_truth(dataset_name: str) -> Optional[Dict]:
    """Load ground truth JSON for a dataset if it exists."""
    # Search both tableau and csv dataset dirs
    for source_type in ("tableau", "csv"):
        gt_dir = PROJECT_ROOT / "config" / "datasets" / source_type / dataset_name
        if not gt_dir.exists():
            continue
        # Find most recent ground truth file
        gt_files = sorted(gt_dir.glob("ground_truth_*.json"), reverse=True)
        if gt_files:
            return json.loads(gt_files[0].read_text(encoding="utf-8"))
    return None


def _extract_numbers_from_brief(brief_md: str) -> List[float]:
    """Extract all numeric values from brief text."""
    # Match: $23.2M, 23,233,591, 15.5%, 2.76, 1,628, etc.
    raw = re.findall(r'[\$]?([\d,]+\.?\d*)\s*[MmBbKk%]?', brief_md)
    numbers = []
    for r in raw:
        try:
            val = float(r.replace(',', ''))
            if val > 0:
                numbers.append(val)
        except ValueError:
            continue
    return numbers


def _number_appears_in_brief(expected: float, brief_md: str, tolerance: float = 0.05) -> bool:
    """Check if a number appears in the brief within tolerance.

    Handles multiple representations:
    - Exact: 23233591
    - Abbreviated: 23.2M, 23.2 million
    - Comma-separated: 23,233,591
    - Rounded: 23.2, 23M
    - Percentage: 15.5%
    """
    if expected is None or expected == 0:
        return False

    brief_lower = brief_md.lower()
    abs_expected = abs(expected)

    # For large numbers, check abbreviated forms (M, K, B)
    if abs_expected >= 1_000_000:
        millions = abs_expected / 1_000_000
        # Check "23.2M", "9.96M", "23.2 million" etc.
        patterns = [
            rf'{millions:.2f}\s*m',
            rf'{millions:.1f}\s*m',
            rf'{millions:.0f}\s*m',
            rf'\${millions:.2f}\s*m',
            rf'\${millions:.1f}\s*m',
            rf'\${millions:.0f}\s*m',
            rf'{millions:.2f}\s*million',
            rf'{millions:.1f}\s*million',
            rf'{millions:.0f}\s*million',
        ]
        for pat in patterns:
            if re.search(pat, brief_lower):
                return True

    if abs_expected >= 1_000:
        thousands = abs_expected / 1_000
        patterns = [
            rf'{thousands:.2f}\s*k',
            rf'{thousands:.1f}\s*k',
            rf'{thousands:.0f}\s*k',
            rf'{thousands:.1f}\s*thousand',
        ]
        for pat in patterns:
            if re.search(pat, brief_lower):
                return True

    # Check all numbers extracted from brief
    brief_numbers = _extract_numbers_from_brief(brief_md)
    for bn in brief_numbers:
        if abs_expected < 1:
            # For small numbers like percentages, use absolute tolerance
            if abs(bn - abs_expected) <= 0.5:
                return True
        elif abs_expected < 100:
            # For KPIs like rev_trk_day=759, deadhead_pct=15.5
            if abs(bn - abs_expected) / abs_expected <= tolerance:
                return True
        else:
            # For large numbers, allow tolerance
            if abs(bn - abs_expected) / abs_expected <= tolerance:
                return True

    return False


def tier0_score(brief_md: str, dataset_name: str) -> Tuple[float, Dict[str, Any]]:
    """Score brief against ground truth data accuracy.

    Returns (score, details_dict). Max 15 points.
    If no ground truth exists, returns (0, {"skipped": True}) — does not penalize.
    """
    gt = _find_ground_truth(dataset_name)
    if not gt:
        return 0.0, {"skipped": True, "reason": "no ground truth file"}

    details: Dict[str, Any] = {"skipped": False}
    network = gt.get("network", {})
    regions = gt.get("regions", {})

    # Use key_metrics if defined — otherwise fall back to all network metrics
    key_metrics = gt.get("key_metrics")

    # --- Network-level accuracy (10 pts) ---
    # Check key network numbers appear in brief
    network_checks = {}
    checked = 0
    found = 0
    check_keys = key_metrics if key_metrics else list(network.keys())
    for key in check_keys:
        expected = network.get(key)
        if expected is None:
            continue
        checked += 1
        present = _number_appears_in_brief(expected, brief_md)
        network_checks[key] = {"expected": expected, "found": present}
        if present:
            found += 1

    if checked > 0:
        network_score = round(10 * found / checked, 1)
    else:
        network_score = 0
    details["network_accuracy"] = network_score
    details["network_found"] = found
    details["network_checked"] = checked
    details["network_checks"] = network_checks

    # --- Regional accuracy (5 pts) ---
    # Check that at least some regional numbers appear
    region_checked = 0
    region_found = 0
    region_details = {}
    for region_name, region_data in regions.items():
        # Check if region name is mentioned
        if region_name.lower() not in brief_md.lower():
            continue
        # Check key values for mentioned regions
        for key in ("ttl_rev_amt", "truck_count", "rev_trk_day", "Revenue xFuel", "Truck Count", "Rev/Trk/Day"):
            expected = region_data.get(key)
            if expected is None:
                continue
            region_checked += 1
            present = _number_appears_in_brief(expected, brief_md)
            region_details[f"{region_name}_{key}"] = {"expected": expected, "found": present}
            if present:
                region_found += 1

    if region_checked > 0:
        region_score = round(5 * region_found / region_checked, 1)
    else:
        region_score = 0
    details["region_accuracy"] = region_score
    details["region_found"] = region_found
    details["region_checked"] = region_checked

    total = round(network_score + region_score, 1)
    return total, details


# ---------------------------------------------------------------------------
# Tier 1: Deterministic structural checks (0-40 points)
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

    Returns (score, details_dict). Max 40 points (rescaled from original 50).
    """
    details: Dict[str, Any] = {}
    score = 0.0

    # 1. JSON validity (4 pts)
    hybrid = brief_json.get("pass2_flat") or brief_json.get("hybrid_pass2_flat") or brief_json.get("hybrid_pipeline_output")
    has_sections = bool(brief_json.get("sections"))
    has_header_body = bool(brief_json.get("header") and brief_json.get("body"))
    if hybrid and isinstance(hybrid, dict):
        details["json_valid"] = 4
        details["json_format"] = "hybrid"
        score += 4
    elif has_sections:
        details["json_valid"] = 4
        details["json_format"] = "sections"
        score += 4
    elif has_header_body:
        details["json_valid"] = 4
        details["json_format"] = "header_body"
        score += 4
    elif brief_json:
        details["json_valid"] = 2
        details["json_format"] = "unknown"
        score += 2
    else:
        details["json_valid"] = 0
        details["json_format"] = "missing"

    # 2. Section completeness (6 pts)
    if hybrid:
        present = sum(1 for s in REQUIRED_SECTIONS if s in hybrid)
        section_score = round(6 * present / len(REQUIRED_SECTIONS), 1)
    elif has_header_body:
        md_lower = brief_md.lower()
        section_keywords = {
            "bottom_line": ["bottom line", "**bottom line"],
            "what_moved": ["what moved", "## what moved"],
            "trend_status": ["trend", "## trend"],
            "where_it_came_from": ["where it came from", "where from", "## where"],
            "why_it_matters": ["why it matters", "## why"],
            "leadership_focus": ["leadership", "## leadership"],
        }
        present = 0
        for section, keywords in section_keywords.items():
            if any(kw in md_lower for kw in keywords):
                present += 1
        section_score = round(6 * present / len(REQUIRED_SECTIONS), 1)
    else:
        sections = brief_json.get("sections", [])
        section_titles = {s.get("title", "").lower().replace(" ", "_") for s in sections}
        present = sum(1 for s in REQUIRED_SECTIONS if any(s in t for t in section_titles))
        section_score = round(6 * present / len(REQUIRED_SECTIONS), 1)
    details["section_completeness"] = section_score
    score += section_score

    # 3. Numeric density (8 pts)
    num_count = _count_numbers(brief_md)
    numeric_score = min(8.0, round(num_count * 0.53, 1))
    details["numeric_density"] = numeric_score
    details["numeric_count"] = num_count
    score += numeric_score

    # 4. Insight card count (6 pts)
    all_cards = _collect_all_insight_cards(metric_jsons)
    total_cards = len(all_cards)
    n_metrics = max(1, len(metric_jsons))
    avg_cards = total_cards / n_metrics
    if avg_cards >= 3:
        card_score = 6
    elif avg_cards >= 1:
        card_score = 3
    elif total_cards >= 1:
        card_score = 1.5
    else:
        card_score = 0
    details["insight_card_count"] = total_cards
    details["insight_card_score"] = card_score
    score += card_score

    # 5. Evidence grounding (8 pts)
    grounded = 0
    total_checked = 0
    for card in all_cards:
        total_checked += 1
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
        evidence_score = round(8 * grounded / total_checked, 1)
    else:
        evidence_score = 0
    details["evidence_grounding"] = evidence_score
    score += evidence_score

    # 6. Contract term compliance (4 pts) — checks raw name OR display name
    metric_names_found = 0
    metric_names_total = 0
    brief_lower = brief_md.lower()
    for mj in metric_jsons:
        name = mj.get("dimension_value", "")
        if name:
            metric_names_total += 1
            # Check raw name variants
            variants = {
                name.lower(),
                name.lower().replace("_", " "),
                name.lower().replace("_", ""),
            }
            # Also check display name from the metric JSON
            display = (mj.get("display_name") or mj.get("brief_label") or "").lower()
            if display:
                variants.add(display)
            words = name.lower().split("_")
            all_words_present = all(w in brief_lower for w in words if len(w) > 2)
            if any(v in brief_lower for v in variants) or all_words_present:
                metric_names_found += 1
    if metric_names_total > 0:
        compliance_score = round(4 * metric_names_found / metric_names_total, 1)
    else:
        compliance_score = 2.0
    details["contract_compliance"] = compliance_score
    score += compliance_score

    # 7. No stub content (4 pts)
    if _has_stub_content(brief_md):
        stub_score = 0
    else:
        stub_score = 4
    details["no_stub"] = stub_score
    score += stub_score

    return round(score, 1), details


# ---------------------------------------------------------------------------
# Tier 2: LLM critic scoring (0-45 points)
# ---------------------------------------------------------------------------

CRITIC_PROMPT_PATH = Path(__file__).parent / "critic_prompt.txt"


def tier2_score(brief_md: str, dataset_desc: str, metrics_list: str) -> Tuple[float, Dict[str, Any]]:
    """Score brief using LLM critic with retry. Returns (score, details_dict). Max 45 points."""
    import time as _time

    prompt_template = CRITIC_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt_template
        .replace("$BRIEF_TEXT$", brief_md)
        .replace("$DATASET_DESCRIPTION$", dataset_desc)
        .replace("$METRICS_LIST$", metrics_list)
    )

    # Load project .env for API key / auth
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    from google import genai
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        client = genai.Client(api_key=api_key)
    else:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        client = genai.Client(vertexai=True, project=project, location=location)

    # Run critic 3x and average to reduce noise
    NUM_CRITIC_RUNS = 3
    all_run_scores: List[Dict[str, int]] = []
    backoff = [2, 5, 10]

    for run_idx in range(NUM_CRITIC_RUNS):
        last_error = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                    ),
                )
                text = response.text.strip()
                text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
                scores = json.loads(text)
                run_scores = {}
                for dim in ["actionability", "causal_depth", "data_specificity", "narrative_coherence", "completeness"]:
                    run_scores[dim] = min(9, max(0, int(scores.get(dim, 0))))
                all_run_scores.append(run_scores)
                break

            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    wait = backoff[attempt]
                    print(f"[evaluate] Tier 2 run {run_idx+1} attempt {attempt+1} failed: {exc}. Retrying in {wait}s...")
                    _time.sleep(wait)
        else:
            print(f"[evaluate] Tier 2 run {run_idx+1} failed after 3 attempts: {last_error}")

    if not all_run_scores:
        return 0.0, {"error": str(last_error), "retries_exhausted": True}

    # Average across runs
    details: Dict[str, Any] = {}
    total = 0
    for dim in ["actionability", "causal_depth", "data_specificity", "narrative_coherence", "completeness"]:
        avg = sum(r[dim] for r in all_run_scores) / len(all_run_scores)
        details[dim] = round(avg, 1)
        total += avg
    details["critic_runs"] = len(all_run_scores)

    # Consistency bonus: if all runs agree within 2 points total, add +1
    if len(all_run_scores) >= 3:
        run_totals = [sum(r.values()) for r in all_run_scores]
        spread = max(run_totals) - min(run_totals)
        if spread <= 2.0:
            total += 1.0
            details["consistency_bonus"] = 1.0
        else:
            details["consistency_bonus"] = 0.0

    return round(total, 1), details


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

    dataset_name = dataset_config.get("name", "")

    t0_score, t0_details = tier0_score(brief_md, dataset_name)
    t1_score, t1_details = tier1_score(brief_json, brief_md, metric_jsons)
    t2_score, t2_details = tier2_score(
        brief_md,
        dataset_config.get("description", ""),
        dataset_config.get("metrics", ""),
    )

    total = round(t0_score + t1_score + t2_score, 1)
    details = {
        "bqs_total": total,
        "tier0_score": t0_score,
        "tier1_score": t1_score,
        "tier2_score": t2_score,
        "tier0_details": t0_details,
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
