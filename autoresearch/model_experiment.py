"""Run targeted model experiments — swap tiers, score, compare."""

import sys
import json
import time
import subprocess
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import EVAL_DATASETS
from evaluate import score_run

PROJECT_ROOT = Path(__file__).parent.parent
MODELS_PATH = PROJECT_ROOT / "config" / "agent_models.yaml"

# Experiments: each is a dict of agent -> new tier
EXPERIMENTS = [
    {
        "name": "baseline (current)",
        "changes": {},
    },
    {
        "name": "narrative=fast (add thinking)",
        "changes": {"narrative_agent": "fast"},
    },
    {
        "name": "narrative=advanced (high thinking)",
        "changes": {"narrative_agent": "advanced"},
    },
    {
        "name": "report_synthesis=advanced + narrative=fast",
        "changes": {"report_synthesis_agent": "advanced", "narrative_agent": "fast"},
    },
    {
        "name": "curator=fast + narrative=fast",
        "changes": {"executive_brief_hybrid_curator": "fast", "narrative_agent": "fast"},
    },
    {
        "name": "all_upgraded: narrative=fast, synthesis=advanced, curator=fast",
        "changes": {
            "narrative_agent": "fast",
            "report_synthesis_agent": "advanced",
            "executive_brief_hybrid_curator": "fast",
        },
    },
]


def load_models_config():
    with open(MODELS_PATH) as f:
        return yaml.safe_load(f)


def save_models_config(config):
    with open(MODELS_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def run_pipeline(dataset_name, metrics, timeout=300):
    import os
    env = os.environ.copy()
    env["ACTIVE_DATASET"] = dataset_name
    cmd = [sys.executable, "-m", "data_analyst_agent", "--dataset", dataset_name, "--metrics", metrics]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(PROJECT_ROOT), env=env)
    # Find latest output
    outputs_dir = PROJECT_ROOT / "outputs" / dataset_name / "global" / "all"
    if outputs_dir.exists():
        dirs = sorted(outputs_dir.iterdir(), key=lambda p: p.name, reverse=True)
        if dirs:
            return str(dirs[0])
    return None


def main():
    original_config = load_models_config()
    results = []

    for exp in EXPERIMENTS:
        print(f"\n{'='*80}")
        print(f"EXPERIMENT: {exp['name']}")
        print(f"{'='*80}")

        # Apply changes
        config = load_models_config()
        for agent, tier in exp["changes"].items():
            if agent in config.get("agents", {}):
                old_tier = config["agents"][agent].get("tier", "?")
                config["agents"][agent]["tier"] = tier
                print(f"  {agent}: {old_tier} -> {tier}")
        save_models_config(config)

        # Score on both datasets
        scores = []
        start = time.time()
        for ds in EVAL_DATASETS:
            print(f"  Running {ds['name']}...")
            output_dir = run_pipeline(ds["name"], ds["metrics"])
            if output_dir:
                bqs, details = score_run(output_dir, ds)
                scores.append(bqs)
                print(f"    BQS={bqs:.1f} (T1={details['tier1_score']:.1f}, T2={details['tier2_score']:.1f})")
            else:
                scores.append(0)
                print(f"    FAILED")
        duration = time.time() - start

        avg = sum(scores) / len(scores) if scores else 0
        results.append({
            "name": exp["name"],
            "avg_bqs": round(avg, 1),
            "scores": scores,
            "duration": round(duration, 0),
        })
        print(f"  AVG BQS: {avg:.1f} | Duration: {duration:.0f}s")

    # Restore original
    save_models_config(original_config)

    # Summary
    print(f"\n{'='*80}")
    print("MODEL EXPERIMENT RESULTS")
    print(f"{'='*80}")
    results.sort(key=lambda r: r["avg_bqs"], reverse=True)
    for i, r in enumerate(results):
        marker = " <-- WINNER" if i == 0 else ""
        print(f"  {r['avg_bqs']:5.1f}  {r['name']} ({r['duration']:.0f}s){marker}")

    # Apply winner if it beats baseline
    winner = results[0]
    baseline = next(r for r in results if r["name"] == "baseline (current)")
    if winner["name"] != "baseline (current)" and winner["avg_bqs"] > baseline["avg_bqs"]:
        print(f"\nApplying winner: {winner['name']} (BQS {winner['avg_bqs']} > baseline {baseline['avg_bqs']})")
        config = load_models_config()
        winning_exp = next(e for e in EXPERIMENTS if e["name"] == winner["name"])
        for agent, tier in winning_exp["changes"].items():
            config["agents"][agent]["tier"] = tier
        save_models_config(config)
        print("Applied. Commit manually if desired.")
    else:
        print(f"\nBaseline wins ({baseline['avg_bqs']}). No changes applied.")


if __name__ == "__main__":
    main()
