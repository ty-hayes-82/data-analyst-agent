"""
Quality evaluation script for model selection experiments.

Compares an experiment's output artifacts against the gold-standard baseline
and generates a comparison_report.md with automated pass/fail checks and
side-by-side excerpts for manual scoring.

Usage:
    python scripts/evaluate_quality.py --baseline results/gold_standard --experiment results/phase_2a
    python scripts/evaluate_quality.py --baseline results/gold_standard --experiment results/phase_3a --output results/phase_3a/comparison.md

Automated checks:
    - Structured extractors: exact-match on request_analysis JSON fields
    - Insight cards: count >= 80% of baseline
    - Executive brief: section headers present, word count within 50%

Manual scoring guide (printed in report):
    Rate each on 1-5: Accuracy (40%), Completeness (25%), Insight Value (20%), Actionability (15%)
    Weighted pass threshold: >= 3.5 overall, >= 4.0 accuracy
    Executive brief higher bar: >= 4.0 overall, >= 4.5 accuracy
"""

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean, median
from typing import Any

import csv


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_request_analysis(stdout_text: str) -> dict | None:
    """Extract the request_analysis JSON object from captured stdout.

    The RequestAnalyzer agent outputs JSON to output_key="request_analysis",
    which appears as the model's text response in the stdout stream.
    """
    pattern = re.compile(
        r'\{[^{}]*"metrics"\s*:\s*\[.*?\][^{}]*\}',
        re.DOTALL,
    )
    for match in pattern.finditer(stdout_text):
        try:
            obj = json.loads(match.group())
            if "metrics" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


def load_all_stdout(result_dir: Path) -> list[tuple[str, str, str]]:
    """Return list of (query_id, run_idx, text) from all stdout_*.txt files."""
    rows = []
    for f in sorted(result_dir.glob("stdout_*.txt")):
        name = f.stem  # stdout_Q1_r1
        parts = name.split("_")
        if len(parts) >= 3:
            qid = parts[1]
            run = parts[2]
        else:
            qid = "unknown"
            run = "r?"
        rows.append((qid, run, f.read_text(encoding="utf-8")))
    return rows


def load_json_artifacts(artifact_dir: Path) -> list[dict]:
    """Load all JSON output artifacts from an artifact directory."""
    items = []
    for f in artifact_dir.glob("*.json"):
        try:
            with f.open(encoding="utf-8") as fp:
                items.append(json.load(fp))
        except Exception:
            pass
    return items


def count_insight_cards(artifacts: list[dict]) -> int:
    """Count total insight cards across all artifact files."""
    total = 0
    for art in artifacts:
        # Insight cards can appear in hierarchical_analysis level results
        hier = art.get("hierarchical_analysis") or {}
        for level_key, level_data in hier.items():
            if isinstance(level_data, dict):
                cards = level_data.get("insight_cards", [])
                if isinstance(cards, list):
                    total += len(cards)
        # Also check top-level narrative_results if present
        narrative = art.get("narrative_results", [])
        if isinstance(narrative, list):
            total += len(narrative)
    return total


def load_markdown_artifacts(artifact_dir: Path) -> list[tuple[str, str]]:
    """Return list of (filename, text) for all markdown files."""
    return [(f.name, f.read_text(encoding="utf-8")) for f in sorted(artifact_dir.glob("*.md"))]


def find_executive_brief(artifact_dir: Path) -> str | None:
    """Find the executive brief markdown in the artifact directory."""
    for f in artifact_dir.glob("executive_brief*.md"):
        return f.read_text(encoding="utf-8")
    return None


def count_words(text: str) -> int:
    return len(text.split())


def find_artifact_dirs(result_dir: Path, query_id: str) -> list[Path]:
    """Find all artifact directories for a given query ID."""
    return sorted(result_dir.glob(f"{query_id}_r*_artifacts"))


# ---------------------------------------------------------------------------
# Automated checks
# ---------------------------------------------------------------------------

class CheckResult:
    def __init__(self, name: str, passed: bool, detail: str, excerpt: str = ""):
        self.name = name
        self.passed = passed
        self.detail = detail
        self.excerpt = excerpt

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}: {self.detail}"


def check_extractor_accuracy(
    baseline_dir: Path, experiment_dir: Path, query_ids: list[str]
) -> list[CheckResult]:
    """Exact-match check on request_analysis fields across all queries."""
    results = []
    baseline_stdouts = {q: r for q, _, r in load_all_stdout(baseline_dir)}
    experiment_stdouts = {q: r for q, _, r in load_all_stdout(experiment_dir)}

    fields_to_match = ["metrics", "primary_dimension", "analysis_type"]

    for qid in query_ids:
        base_text = baseline_stdouts.get(qid, "")
        exp_text = experiment_stdouts.get(qid, "")

        base_ra = parse_request_analysis(base_text)
        exp_ra = parse_request_analysis(exp_text)

        if not base_ra:
            results.append(CheckResult(
                f"extractor/{qid}/parse",
                False,
                "Could not parse request_analysis from baseline stdout",
            ))
            continue

        if not exp_ra:
            results.append(CheckResult(
                f"extractor/{qid}/parse",
                False,
                "Could not parse request_analysis from experiment stdout",
            ))
            continue

        for field in fields_to_match:
            base_val = base_ra.get(field)
            exp_val = exp_ra.get(field)
            matched = _normalize_field(base_val) == _normalize_field(exp_val)
            detail = f"baseline={base_val!r} experiment={exp_val!r}"
            results.append(CheckResult(
                f"extractor/{qid}/{field}",
                matched,
                detail,
                excerpt=f"  baseline:   {field}={json.dumps(base_val)}\n  experiment: {field}={json.dumps(exp_val)}",
            ))

    return results


def _normalize_field(val: Any) -> Any:
    """Normalize a field value for comparison (lower-case lists, etc.)."""
    if isinstance(val, list):
        return sorted([str(v).strip().lower() for v in val])
    if isinstance(val, str):
        return val.strip().lower()
    return val


def check_insight_card_count(
    baseline_dir: Path, experiment_dir: Path, query_ids: list[str], threshold: float = 0.8
) -> list[CheckResult]:
    """Check that insight card count >= threshold * baseline count."""
    results = []

    for qid in query_ids:
        base_artifact_dirs = find_artifact_dirs(baseline_dir, qid)
        exp_artifact_dirs = find_artifact_dirs(experiment_dir, qid)

        base_cards = sum(count_insight_cards(load_json_artifacts(d)) for d in base_artifact_dirs)
        exp_cards = sum(count_insight_cards(load_json_artifacts(d)) for d in exp_artifact_dirs)

        if base_cards == 0:
            results.append(CheckResult(
                f"insight_cards/{qid}",
                True,
                f"Baseline has 0 cards — skipping ratio check (exp={exp_cards})",
            ))
            continue

        ratio = exp_cards / base_cards
        passed = ratio >= threshold
        detail = f"baseline={base_cards} experiment={exp_cards} ratio={ratio:.2f} (threshold={threshold:.0%})"
        results.append(CheckResult(f"insight_cards/{qid}", passed, detail))

    return results


def check_executive_brief(
    baseline_dir: Path, experiment_dir: Path, query_ids: list[str]
) -> list[CheckResult]:
    """Check executive brief structure and word count."""
    results = []
    required_sections = ["summary", "key pattern", "watch"]

    for qid in query_ids:
        base_artifact_dirs = find_artifact_dirs(baseline_dir, qid)
        exp_artifact_dirs = find_artifact_dirs(experiment_dir, qid)

        base_brief = None
        for d in base_artifact_dirs:
            base_brief = find_executive_brief(d)
            if base_brief:
                break

        exp_brief = None
        for d in exp_artifact_dirs:
            exp_brief = find_executive_brief(d)
            if exp_brief:
                break

        if not base_brief:
            results.append(CheckResult(
                f"exec_brief/{qid}/present",
                True,
                "No baseline brief — skipping checks for this query",
            ))
            continue

        if not exp_brief:
            results.append(CheckResult(
                f"exec_brief/{qid}/present",
                False,
                "Executive brief missing in experiment output",
            ))
            continue

        # Section header check
        exp_lower = exp_brief.lower()
        for section in required_sections:
            found = section in exp_lower
            results.append(CheckResult(
                f"exec_brief/{qid}/section/{section.replace(' ', '_')}",
                found,
                f"Section '{section}' {'found' if found else 'MISSING'}",
                excerpt=f"  First 200 chars: {exp_brief[:200]!r}",
            ))

        # Word count check (within 50% of baseline)
        base_words = count_words(base_brief)
        exp_words = count_words(exp_brief)
        ratio = exp_words / base_words if base_words else 1.0
        in_range = 0.5 <= ratio <= 1.5
        results.append(CheckResult(
            f"exec_brief/{qid}/word_count",
            in_range,
            f"baseline={base_words} words, experiment={exp_words} words, ratio={ratio:.2f}",
        ))

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(
    baseline_dir: Path,
    experiment_dir: Path,
    output_path: Path,
    query_ids: list[str],
) -> None:
    """Run all checks and write comparison_report.md."""

    print(f"\n[evaluate] Baseline : {baseline_dir}")
    print(f"[evaluate] Experiment: {experiment_dir}")
    print(f"[evaluate] Report    : {output_path}\n")

    all_checks: list[CheckResult] = []

    print("[evaluate] Running extractor accuracy checks...")
    extractor_checks = check_extractor_accuracy(baseline_dir, experiment_dir, query_ids)
    all_checks.extend(extractor_checks)

    print("[evaluate] Running insight card count checks...")
    card_checks = check_insight_card_count(baseline_dir, experiment_dir, query_ids)
    all_checks.extend(card_checks)

    print("[evaluate] Running executive brief checks...")
    brief_checks = check_executive_brief(baseline_dir, experiment_dir, query_ids)
    all_checks.extend(brief_checks)

    passed = [c for c in all_checks if c.passed]
    failed = [c for c in all_checks if not c.passed]

    # Print quick summary to console
    print(f"\n[evaluate] Results: {len(passed)} passed, {len(failed)} failed\n")
    for c in failed:
        print(f"  FAIL: {c.name}: {c.detail}")

    # Write markdown report
    lines = []
    lines.append(f"# Quality Comparison Report")
    lines.append(f"")
    lines.append(f"**Baseline**: `{baseline_dir}`  ")
    lines.append(f"**Experiment**: `{experiment_dir}`  ")
    lines.append(f"**Generated**: {_now()}")
    lines.append(f"")
    lines.append(f"## Automated Check Summary")
    lines.append(f"")
    lines.append(f"| Result | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| PASS | {len(passed)} |")
    lines.append(f"| FAIL | {len(failed)} |")
    lines.append(f"| Total | {len(all_checks)} |")
    lines.append(f"")

    if failed:
        lines.append(f"## Failed Checks")
        lines.append(f"")
        for c in failed:
            lines.append(f"- **{c.name}**: {c.detail}")
            if c.excerpt:
                lines.append(f"")
                lines.append(f"  ```")
                lines.append(f"  {c.excerpt.strip()}")
                lines.append(f"  ```")
        lines.append(f"")

    lines.append(f"## All Checks Detail")
    lines.append(f"")
    lines.append(f"| Status | Check | Detail |")
    lines.append(f"|--------|-------|--------|")
    for c in all_checks:
        status = "PASS" if c.passed else "**FAIL**"
        lines.append(f"| {status} | `{c.name}` | {c.detail} |")
    lines.append(f"")

    lines.append(f"## Manual Scoring Guide")
    lines.append(f"")
    lines.append(f"For agents that passed automated checks, manually score their output on:")
    lines.append(f"")
    lines.append(f"| Dimension | Weight | Definition |")
    lines.append(f"|-----------|--------|-----------|")
    lines.append(f"| Accuracy | 40% | Numbers, names, relationships match source data |")
    lines.append(f"| Completeness | 25% | All material findings are surfaced |")
    lines.append(f"| Insight Value | 20% | Non-obvious patterns identified |")
    lines.append(f"| Actionability | 15% | Output enables a decision or follow-up |")
    lines.append(f"")
    lines.append(f"**Pass thresholds**:")
    lines.append(f"- Most agents: weighted score >= 3.5 AND Accuracy >= 4.0")
    lines.append(f"- Executive brief: weighted score >= 4.0 AND Accuracy >= 4.5")
    lines.append(f"")
    lines.append(f"### Decision Matrix (fill in manually)")
    lines.append(f"")
    lines.append(f"| Agent | Accuracy | Completeness | Insight Value | Actionability | Weighted | Pass? |")
    lines.append(f"|-------|---------|-------------|--------------|--------------|---------|-------|")
    for agent in ["request_analyzer", "dimension_extractor", "narrative_agent", "report_synthesis_agent", "seasonal_baseline_agent", "executive_brief_agent"]:
        lines.append(f"| `{agent}` | /5 | /5 | /5 | /5 | /5 | |")
    lines.append(f"")

    lines.append(f"## Output Excerpts for Manual Review")
    lines.append(f"")

    # Sample excerpts from experiment artifacts
    for qid in query_ids:
        lines.append(f"### Query {qid}")
        lines.append(f"")
        exp_artifact_dirs = find_artifact_dirs(experiment_dir, qid)
        if not exp_artifact_dirs:
            lines.append(f"_No artifact directories found for {qid}_")
            lines.append(f"")
            continue

        # Show first markdown report
        for adir in exp_artifact_dirs[:1]:
            mds = load_markdown_artifacts(adir)
            if mds:
                fname, text = mds[0]
                lines.append(f"**{fname}** (first 800 chars):")
                lines.append(f"")
                lines.append(f"```markdown")
                lines.append(text[:800])
                lines.append(f"```")
                lines.append(f"")

            # Show executive brief if present
            brief = find_executive_brief(adir)
            if brief:
                lines.append(f"**Executive Brief** (first 600 chars):")
                lines.append(f"")
                lines.append(f"```markdown")
                lines.append(brief[:600])
                lines.append(f"```")
                lines.append(f"")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[evaluate] Report written: {output_path}")


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compare experiment outputs against baseline for quality evaluation."
    )
    parser.add_argument(
        "--baseline",
        required=True,
        help="Path to the baseline results directory (gold standard).",
    )
    parser.add_argument(
        "--experiment",
        required=True,
        help="Path to the experiment results directory to evaluate.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path for the output comparison_report.md. Defaults to <experiment>/comparison.md.",
    )
    parser.add_argument(
        "--queries",
        nargs="+",
        default=["Q1", "Q2", "Q3"],
        help="Query IDs to evaluate (default: Q1 Q2 Q3).",
    )
    args = parser.parse_args()

    baseline_dir = Path(args.baseline)
    experiment_dir = Path(args.experiment)

    if not baseline_dir.exists():
        print(f"ERROR: Baseline directory not found: {baseline_dir}")
        sys.exit(1)
    if not experiment_dir.exists():
        print(f"ERROR: Experiment directory not found: {experiment_dir}")
        sys.exit(1)

    output_path = Path(args.output) if args.output else experiment_dir / "comparison.md"

    generate_report(
        baseline_dir=baseline_dir,
        experiment_dir=experiment_dir,
        output_path=output_path,
        query_ids=args.queries,
    )


if __name__ == "__main__":
    main()
