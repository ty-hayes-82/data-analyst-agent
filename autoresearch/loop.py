"""
Autonomous experimentation loop for data-analyst-agent pipeline optimization.

Adapts the Karpathy autoresearch pattern: modify -> run -> score -> keep/discard -> repeat.

Usage:
    python autoresearch/loop.py [--max-iterations N] [--budget DOLLARS]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import EVAL_DATASETS
from evaluate import score_run
from run_experiment import run_pipeline, find_latest_output

PROJECT_ROOT = Path(__file__).parent.parent
RESULTS_TSV = Path(__file__).parent / "results.tsv"
BASELINE_PATH = Path(__file__).parent / "baseline_scores.json"

# Budget defaults
DEFAULT_MAX_ITERATIONS = 20
DEFAULT_BUDGET = 2.0  # dollars per session
COST_PER_EXPERIMENT = 0.09  # estimated


# ---------------------------------------------------------------------------
# Mutation targets (ordered by priority)
# ---------------------------------------------------------------------------

MUTATION_TARGETS = [
    # --- Model selection layer (highest priority — test different models) ---
    {
        "name": "agent_models",
        "path": "config/agent_models.yaml",
        "type": "config",
        "brief_only": False,
        "description": "Model tier assignments per agent. Each agent has a safe_tiers list — you MUST only use tiers from that list. CRITICAL: JSON-output agents (narrative_agent, statistical_insights_agent, executive_brief_agent, executive_brief_hybrid_curator) CANNOT use thinking tiers (fast/advanced/pro) — thinking corrupts JSON output. Text-output agents (report_synthesis_agent, executive_brief_hybrid_synthesis, hierarchical_analysis_agent) CAN use thinking tiers. Key experiments: try 'standard' for narrative_agent (currently brief), try 'advanced' or 'pro' for executive_brief_hybrid_synthesis, try 'pro' for report_synthesis_agent. Only change ONE agent tier per experiment. Check the safe_tiers field for each agent before proposing a change.",
    },
    # --- Output layer (presentation) — brief_only: reuse cached analysis ---
    {
        "name": "executive_brief_ceo_prompt",
        "path": "config/prompts/executive_brief_ceo.md",
        "type": "prompt",
        "brief_only": True,
        "description": "CEO executive brief generation prompt — controls final brief structure, voice, and formatting",
    },
    {
        "name": "report_synthesis_prompt",
        "path": "config/prompts/report_synthesis.md",
        "type": "prompt",
        "brief_only": True,
        "description": "Report synthesis prompt — assembles all analysis results into a structured executive markdown",
    },
    {
        "name": "narrative_prompt",
        "path": "data_analyst_agent/sub_agents/narrative_agent/prompt.py",
        "type": "prompt",
        "brief_only": False,
        "description": "Narrative agent instruction — generates semantic insight cards from hierarchy/stats results",
    },
    {
        "name": "executive_brief_base_prompt",
        "path": "config/prompts/executive_brief.md",
        "type": "prompt",
        "brief_only": True,
        "description": "Base executive brief prompt template — non-CEO style brief generation",
    },
    # --- Analysis layer (deeper quality) — full pipeline required ---
    {
        "name": "statistical_insights_prompt",
        "path": "data_analyst_agent/sub_agents/statistical_insights_agent/prompt.py",
        "type": "prompt",
        "brief_only": False,
        "description": "Statistical insights agent — controls what statistical patterns are detected (variance, trends, outliers, rolling averages)",
    },
    {
        "name": "hierarchy_variance_prompt",
        "path": "data_analyst_agent/sub_agents/hierarchy_variance_agent/prompt.py",
        "type": "prompt",
        "brief_only": False,
        "description": "Hierarchy variance agent — controls drill-down logic, entity ranking, concentration analysis, and variance decomposition",
    },
    {
        "name": "alert_scoring_prompt",
        "path": "data_analyst_agent/sub_agents/alert_scoring_agent/prompt.py",
        "type": "prompt",
        "brief_only": False,
        "description": "Alert scoring agent — controls anomaly detection sensitivity, threshold scoring, and severity classification",
    },
    {
        "name": "planner_prompt",
        "path": "data_analyst_agent/sub_agents/planner_agent/prompt.py",
        "type": "prompt",
        "brief_only": False,
        "description": "Planner agent — determines which analysis agents run and in what order based on data characteristics",
    },
    {
        "name": "report_synthesis_agent_prompt",
        "path": "data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py",
        "type": "prompt",
        "brief_only": True,
        "description": "Report synthesis agent prompt.py — the agent-level synthesis prompt (separate from config .md)",
    },
    {
        "name": "executive_brief_agent_prompt",
        "path": "data_analyst_agent/sub_agents/executive_brief_agent/prompt.py",
        "type": "prompt",
        "brief_only": True,
        "description": "Executive brief agent prompt.py — controls brief generation logic, scoped briefs, and hybrid pipeline behavior",
    },
    # --- Code targets REMOVED — every code mutation in logs either crashed T1 or was discarded.
    # Code changes require manual implementation, not LLM find/replace. ---
    {
        "name": "executive_brief_ceo_lite_prompt",
        "path": "config/prompts/executive_brief_ceo_lite.md",
        "type": "prompt",
        "brief_only": True,
        "description": "CEO Lite prompt — the Pass1 curation prompt that filters and ranks insights before the final synthesis. Controls which signals survive to the final brief.",
    },
]


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short=7", "HEAD"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    return result.stdout.strip()


def git_commit(message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=PROJECT_ROOT, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=PROJECT_ROOT, capture_output=True,
    )
    return git_sha()


def git_reset_hard() -> None:
    subprocess.run(
        ["git", "reset", "--hard", "HEAD~1"],
        cwd=PROJECT_ROOT, capture_output=True,
    )


def git_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Mutation generation
# ---------------------------------------------------------------------------

def generate_mutation(target: Dict[str, Any], recent_results: List[Dict]) -> Optional[Dict[str, Any]]:
    """Use LLM to propose a specific modification to the target file."""
    file_path = PROJECT_ROOT / target["path"]
    if not file_path.exists():
        print(f"[loop] Target file not found: {file_path}")
        return None

    current_content = file_path.read_text(encoding="utf-8")

    # Truncate very long files for the mutation prompt
    if len(current_content) > 8000:
        current_content = current_content[:4000] + "\n\n... [truncated] ...\n\n" + current_content[-4000:]

    recent_str = ""
    for r in recent_results[-5:]:
        recent_str += f"  iter {r.get('iteration', '?')}: {r.get('status', '?')} (BQS {r.get('bqs_total', '?')}) - {r.get('description', '?')}\n"

    prompt = f"""You are optimizing a data analysis pipeline's output quality.

The scoring rubric measures: actionability (concrete recommendations), causal depth (explains WHY),
data specificity (exact numbers), narrative coherence (logical story), completeness (all metrics covered).

Current file: {target['path']}
Description: {target['description']}

Current content:
---
{current_content}
---

Recent experiment results:
{recent_str if recent_str else '  (no prior experiments)'}

Propose ONE specific, small modification to improve the Brief Quality Score.
- Change one thing at a time
- Keep it simple — a small targeted improvement
- Focus on the scoring dimensions that are weakest
- Provide the EXACT text to find and the EXACT replacement text

IMPORTANT: Return a JSON with THREE fields:
- "description": a short summary of what you changed
- "find": the exact substring from the current file to replace (copy-paste it exactly)
- "replace": the new text to put in its place

Keep "find" and "replace" SHORT — just the specific lines you are changing, not the whole file.

Example: {{"description": "Added causal explanation requirement", "find": "Explain what changed.", "replace": "Explain what changed and WHY it changed, citing the root cause."}}
"""

    try:
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

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json",
            ),
        )
        result = _parse_mutation_json(response.text)
        if not result:
            print("[loop] Failed to parse mutation JSON from LLM response")
            return None

        # Build the new file content by applying the find/replace
        original_content = file_path.read_text(encoding="utf-8")
        find_str = result.get("find", "")
        replace_str = result.get("replace", "")

        if not find_str or not replace_str:
            # Fallback: check if LLM returned new_content instead (old format)
            if result.get("new_content"):
                return {
                    "target": target,
                    "description": result.get("description", "unknown mutation"),
                    "new_content": result["new_content"],
                    "original_content": original_content,
                }
            print("[loop] Mutation has empty find or replace, skipping")
            return None

        if find_str not in original_content:
            print(f"[loop] Find string not found in file (len={len(find_str)}), skipping")
            return None

        new_content = original_content.replace(find_str, replace_str, 1)
        return {
            "target": target,
            "description": result.get("description", "unknown mutation"),
            "new_content": new_content,
            "original_content": original_content,
        }
    except Exception as exc:
        print(f"[loop] Mutation generation failed: {exc}")
        return None


def _parse_mutation_json(raw_text: str) -> Optional[Dict[str, Any]]:
    """Parse mutation JSON with control char stripping."""
    text = raw_text.strip()
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[loop] JSON parse error: {e}")
        return None


def apply_mutation(mutation: Dict[str, Any]) -> bool:
    """Write the mutated content to the target file. Validates syntax for code targets."""
    file_path = PROJECT_ROOT / mutation["target"]["path"]
    new_content = mutation.get("new_content", "")
    if not new_content or len(new_content) < 50:
        print("[loop] Mutation content too short, skipping")
        return False
    file_path.write_text(new_content, encoding="utf-8")

    # Syntax check for Python code targets
    if mutation["target"].get("type") == "code" and file_path.suffix == ".py":
        result = subprocess.run(
            [sys.executable, "-c", f"compile(open('{file_path}').read(), '{file_path}', 'exec')"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        if result.returncode != 0:
            print(f"[loop] SYNTAX ERROR in {file_path.name}: {result.stderr.strip()[-200:]}")
            file_path.write_text(mutation["original_content"], encoding="utf-8")
            return False

    # Safe tier validation for agent_models changes
    if mutation["target"].get("name") == "agent_models" and file_path.suffix in (".yaml", ".yml"):
        import yaml as _yaml
        try:
            config = _yaml.safe_load(new_content)
            agents = config.get("agents", {})
            tiers = config.get("model_tiers", {})
            for agent_name, agent_cfg in agents.items():
                tier = agent_cfg.get("tier", "")
                safe = agent_cfg.get("safe_tiers", [])
                if safe and tier not in safe:
                    print(f"[loop] UNSAFE TIER: {agent_name} set to '{tier}' but safe_tiers={safe}")
                    file_path.write_text(mutation["original_content"], encoding="utf-8")
                    return False
                if tier and tier not in tiers:
                    print(f"[loop] UNKNOWN TIER: {agent_name} set to '{tier}' which is not in model_tiers")
                    file_path.write_text(mutation["original_content"], encoding="utf-8")
                    return False
        except Exception as e:
            print(f"[loop] YAML PARSE ERROR in agent_models: {e}")
            file_path.write_text(mutation["original_content"], encoding="utf-8")
            return False

    print(f"[loop] Applied mutation to {mutation['target']['path']}")
    return True


def revert_mutation(mutation: Dict[str, Any]) -> None:
    """Restore the original file content."""
    file_path = PROJECT_ROOT / mutation["target"]["path"]
    file_path.write_text(mutation["original_content"], encoding="utf-8")


# ---------------------------------------------------------------------------
# Results logging
# ---------------------------------------------------------------------------

def load_results() -> List[Dict]:
    """Load results from TSV."""
    results = []
    if RESULTS_TSV.exists():
        with open(RESULTS_TSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                results.append(row)
    return results


def log_result(
    iteration: int,
    commit: str,
    bqs_total: float,
    tier0: float,
    tier1: float,
    tier2: float,
    status: str,
    target: str,
    description: str,
    duration: float,
) -> None:
    """Append a result to the TSV."""
    exists = RESULTS_TSV.exists()
    with open(RESULTS_TSV, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        if not exists:
            writer.writerow([
                "timestamp", "iteration", "commit", "bqs_total",
                "tier0_score", "tier1_score", "tier2_score", "status", "mutation_target", "description", "duration_sec",
            ])
        writer.writerow([
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            iteration, commit, f"{bqs_total:.1f}",
            f"{tier0:.1f}", f"{tier1:.1f}", f"{tier2:.1f}",
            status, target, description, f"{duration:.0f}",
        ])


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_and_score_all(datasets: List[Dict]) -> Tuple[float, float, float, float, Dict]:
    """Run pipeline on all eval datasets. Returns (avg_bqs, avg_t0, avg_t1, avg_t2, details)."""
    all_scores = []
    all_t0 = []
    all_t1 = []
    all_t2 = []
    all_details = {}

    for ds in datasets:
        print(f"\n[loop] Running pipeline: {ds['name']} / {ds['metrics']}")
        try:
            output_dir = run_pipeline(ds["name"], ds["metrics"], extra_args=ds.get("extra_args"))
            if output_dir:
                bqs, details = score_run(output_dir, ds)
                all_scores.append(bqs)
                all_t0.append(details.get("tier0_score", 0))
                all_t1.append(details["tier1_score"])
                all_t2.append(details["tier2_score"])
                all_details[ds["name"]] = details
                t0 = details.get("tier0_score", 0)
                print(f"[loop] {ds['name']}: BQS={bqs:.1f} (T0={t0:.1f}, T1={details['tier1_score']:.1f}, T2={details['tier2_score']:.1f})")
            else:
                print(f"[loop] {ds['name']}: Pipeline failed, scoring 0")
                all_scores.append(0)
                all_t0.append(0)
                all_t1.append(0)
                all_t2.append(0)
        except Exception as exc:
            print(f"[loop] {ds['name']}: Error: {exc}")
            all_scores.append(0)
            all_t0.append(0)
            all_t1.append(0)
            all_t2.append(0)

    # Weighted average (default weight=1.0 if not specified)
    weights = [ds.get("weight", 1.0) for ds in datasets]
    total_w = sum(weights[:len(all_scores)]) or 1
    avg_bqs = sum(s * w for s, w in zip(all_scores, weights)) / total_w if all_scores else 0
    avg_t0 = sum(s * w for s, w in zip(all_t0, weights)) / total_w if all_t0 else 0
    avg_t1 = sum(s * w for s, w in zip(all_t1, weights)) / total_w if all_t1 else 0
    avg_t2 = sum(s * w for s, w in zip(all_t2, weights)) / total_w if all_t2 else 0
    return round(avg_bqs, 1), round(avg_t0, 1), round(avg_t1, 1), round(avg_t2, 1), all_details


def pick_target(results: List[Dict]) -> Dict[str, Any]:
    """Pick a mutation target with weighted random selection.

    Prompt targets get weight 3 (safer, higher leverage).
    Code targets get weight 1 (riskier, can break syntax).
    """
    type_weights = {"prompt": 2, "config": 5, "code": 1}
    weights = [type_weights.get(t.get("type", "code"), 1) for t in MUTATION_TARGETS]
    return random.choices(MUTATION_TARGETS, weights=weights, k=1)[0]


def main():
    parser = argparse.ArgumentParser(description="Autoresearch loop for data-analyst-agent")
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET)
    args = parser.parse_args()

    branch = git_branch()
    if not branch:
        print("[loop] ERROR: Not in a git repository or cannot determine branch")
        sys.exit(1)

    print(f"\n{'='*80}")
    print(f"AUTORESEARCH LOOP")
    print(f"  Branch: {branch}")
    print(f"  Max iterations: {args.max_iterations}")
    print(f"  Budget: ${args.budget:.2f}")
    print(f"  Datasets: {', '.join(d['name'] for d in EVAL_DATASETS)}")
    print(f"{'='*80}\n")

    # --- Baseline ---
    print("[loop] Running baseline...")
    start = time.time()
    best_bqs, best_t0, best_t1, best_t2, baseline_details = run_and_score_all(EVAL_DATASETS)
    baseline_duration = time.time() - start

    BASELINE_PATH.write_text(json.dumps(baseline_details, indent=2), encoding="utf-8")
    log_result(0, git_sha(), best_bqs, best_t0, best_t1, best_t2, "baseline", "-", "Initial baseline", baseline_duration)
    print(f"\n[loop] BASELINE: BQS={best_bqs:.1f} (T0={best_t0:.1f}, T1={best_t1:.1f}, T2={best_t2:.1f})")

    estimated_cost = 0.0
    results = load_results()
    consecutive_discards = 0
    last_target_type = None

    # --- Experiment loop ---
    for iteration in range(1, args.max_iterations + 1):
        if estimated_cost >= args.budget:
            print(f"\n[loop] Budget limit reached (${estimated_cost:.2f} >= ${args.budget:.2f}). Stopping.")
            break

        print(f"\n{'='*80}")
        print(f"ITERATION {iteration}/{args.max_iterations}")
        print(f"  Best BQS: {best_bqs:.1f}  |  Est. cost: ${estimated_cost:.2f}/{args.budget:.2f}")
        print(f"  Consecutive discards: {consecutive_discards}")
        print(f"{'='*80}")

        start = time.time()

        # 1. Pick target — force diversity after 5 consecutive discards on same type
        target = pick_target(results)
        if consecutive_discards >= 5 and last_target_type:
            # Force a different target type
            alt_targets = [t for t in MUTATION_TARGETS if t.get("type") != last_target_type]
            if alt_targets:
                target = random.choice(alt_targets)
                print(f"[loop] Diversity bonus: switching from {last_target_type} to {target.get('type')} targets")
                consecutive_discards = 0

        print(f"[loop] Target: {target['name']} ({target['path']})")

        mutation = generate_mutation(target, results)
        if not mutation:
            print("[loop] Failed to generate mutation, skipping")
            continue

        print(f"[loop] Mutation: {mutation['description']}")

        # 2. Apply mutation and commit
        if not apply_mutation(mutation):
            continue

        sha = git_commit(f"[autoresearch] iter {iteration}: {mutation['description']}")

        # 3. Run and score
        bqs, t0, t1, t2, details = run_and_score_all(EVAL_DATASETS)
        duration = time.time() - start
        estimated_cost += COST_PER_EXPERIMENT

        # 4. Keep or discard (margin of -0.5 allows near-ties without score drift)
        if bqs >= best_bqs - 0.5:
            status = "keep"
            best_bqs = bqs
            best_t0 = t0
            best_t1 = t1
            best_t2 = t2
            consecutive_discards = 0
            print(f"\n[loop] >>> KEEP: BQS {bqs:.1f} >= {best_bqs:.1f}")
        else:
            status = "discard"
            git_reset_hard()
            consecutive_discards += 1
            last_target_type = target.get("type")
            print(f"\n[loop] <<< DISCARD: BQS {bqs:.1f} < {best_bqs:.1f}")

        # 5. Log
        log_result(
            iteration, sha if status == "keep" else "discarded",
            bqs, t0, t1, t2, status, target["name"],
            mutation["description"], duration,
        )
        results = load_results()

    # --- Summary ---
    print(f"\n{'='*80}")
    print(f"AUTORESEARCH COMPLETE")
    print(f"  Iterations: {iteration if 'iteration' in dir() else 0}")
    print(f"  Final BQS: {best_bqs:.1f}")
    print(f"  Est. cost: ${estimated_cost:.2f}")
    kept = sum(1 for r in results if r.get("status") == "keep")
    print(f"  Kept: {kept}/{len(results)-1} experiments")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
