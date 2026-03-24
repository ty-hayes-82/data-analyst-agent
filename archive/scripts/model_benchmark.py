#!/usr/bin/env python3
"""Benchmark executive brief generation across model/settings combinations.

Uses cached insight cards so the full analysis pipeline doesn't need to re-run.
For each variant in the chosen matrix, generates a temporary agent_models.yaml,
applies it via set_config_override(), loads the cached digest, and records the
configuration for later comparison.

Usage:
    python scripts/model_benchmark.py \
        --cache-dir outputs/2026-03-19/.cache \
        --matrix brief \
        --output-dir benchmark_results/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Ensure the project root is importable
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from config.model_loader import clear_config_override, set_config_override  # noqa: E402
from data_analyst_agent.cache.insight_cache import InsightCache  # noqa: E402

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ModelVariant:
    """One model/settings combination to benchmark."""

    label: str
    model: str
    temperature: float
    thinking_budget: int | None = None
    thinking_level: str | None = None

    def tier_dict(self) -> dict[str, Any]:
        """Return a tier config dict suitable for agent_models.yaml."""
        d: dict[str, Any] = {
            "model": self.model,
            "description": f"Benchmark variant: {self.label}",
        }
        if self.thinking_budget is not None:
            d["thinking_budget"] = self.thinking_budget
        if self.thinking_level is not None:
            d["thinking_level"] = self.thinking_level
        else:
            d["thinking_level"] = "none"
        return d


@dataclass
class BenchmarkResult:
    """Result record for one variant run."""

    variant: str
    matrix: str
    model: str
    temperature: float
    thinking_budget: int | None
    thinking_level: str | None
    config_path: str
    digest_loaded: bool
    status: str  # "ok" | "no_digest" | "error"
    error: str | None = None


# ---------------------------------------------------------------------------
# Test matrices
# ---------------------------------------------------------------------------

BRIEF_MATRIX: list[ModelVariant] = [
    ModelVariant("flash-2.5-t0.2-no-think", "gemini-2.5-flash", 0.2),
    ModelVariant("flash-2.5-t0.3-tb512", "gemini-2.5-flash", 0.3, thinking_budget=512),
    ModelVariant("flash-2.5-t0.3-tb1024", "gemini-2.5-flash", 0.3, thinking_budget=1024),
    ModelVariant("flash-2.5-t0.4-tb2048", "gemini-2.5-flash", 0.4, thinking_budget=2048),
    ModelVariant("flash-lite-t0.2-no-think", "gemini-2.5-flash-lite", 0.2),
    ModelVariant("flash-3-t0.3-think-med", "gemini-3-flash-preview", 0.3, thinking_level="medium"),
    ModelVariant("flash-3-t0.3-tb14000", "gemini-3-flash-preview", 0.3, thinking_budget=14000),
]

NARRATIVE_MATRIX: list[ModelVariant] = [
    ModelVariant("flash-2.5-t0.1-tb4096", "gemini-2.5-flash", 0.1, thinking_budget=4096),
    ModelVariant("flash-2.5-t0.15-tb8192", "gemini-2.5-flash", 0.15, thinking_budget=8192),
    ModelVariant("flash-2.5-t0.2-tb8192", "gemini-2.5-flash", 0.2, thinking_budget=8192),
    ModelVariant("flash-lite-t0.1-no-think", "gemini-2.5-flash-lite", 0.1),
]

SYNTHESIS_MATRIX: list[ModelVariant] = [
    ModelVariant("flash-2.5-t0.1-no-think", "gemini-2.5-flash", 0.1),
    ModelVariant("flash-lite-t0.1-no-think", "gemini-2.5-flash-lite", 0.1),
    ModelVariant("flash-2.5-t0.15-tb512", "gemini-2.5-flash", 0.15, thinking_budget=512),
]

MATRICES: dict[str, list[ModelVariant]] = {
    "brief": BRIEF_MATRIX,
    "narrative": NARRATIVE_MATRIX,
    "synthesis": SYNTHESIS_MATRIX,
}

# Map matrix name -> the agent that would be invoked
MATRIX_AGENT: dict[str, str] = {
    "brief": "executive_brief_agent",
    "narrative": "narrative_agent",
    "synthesis": "report_synthesis_agent",
}

# ---------------------------------------------------------------------------
# YAML generation
# ---------------------------------------------------------------------------

# Load the base config once so we can overlay variants on top of real settings.
_BASE_CONFIG_PATH = _PROJECT_ROOT / "config" / "agent_models.yaml"


def _load_base_config() -> dict[str, Any]:
    with open(_BASE_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_variant_config(
    variant: ModelVariant,
    agent_name: str,
) -> dict[str, Any]:
    """Build a full agent_models.yaml dict with *variant* injected as a
    custom tier assigned to *agent_name*."""
    config = _load_base_config()

    tier_name = f"benchmark_{variant.label.replace('-', '_')}"
    config["model_tiers"][tier_name] = variant.tier_dict()

    # Point the target agent at the benchmark tier
    if agent_name not in config.get("agents", {}):
        config.setdefault("agents", {})[agent_name] = {}
    config["agents"][agent_name]["tier"] = tier_name

    return config


def write_temp_config(config: dict[str, Any], output_dir: Path, label: str) -> Path:
    """Write a variant config to *output_dir* and return the path."""
    path = output_dir / f"agent_models_{label}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    return path


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


def run_variant(
    variant: ModelVariant,
    matrix_name: str,
    cache: InsightCache,
    output_dir: Path,
) -> BenchmarkResult:
    """Run a single variant: generate config, apply override, load digest."""
    agent_name = MATRIX_AGENT[matrix_name]

    # 1. Generate and write the config
    config = generate_variant_config(variant, agent_name)
    config_path = write_temp_config(config, output_dir, variant.label)

    # 2. Apply override
    set_config_override(str(config_path))

    # 3. Load cached digest
    digest = cache.get_digest()
    digest_loaded = digest is not None

    # 4. Save the variant record (config + digest snippet) for later review
    record: dict[str, Any] = {
        "variant": variant.label,
        "matrix": matrix_name,
        "model": variant.model,
        "temperature": variant.temperature,
        "thinking_budget": variant.thinking_budget,
        "thinking_level": variant.thinking_level,
        "digest_loaded": digest_loaded,
        "config_path": str(config_path),
    }
    if digest is not None:
        record["digest_metric_count"] = len(digest.get("metrics", []))
        record["digest_keys"] = list(digest.keys())

    record_path = output_dir / f"result_{variant.label}.json"
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)

    # 5. Clear override so next variant starts clean
    clear_config_override()

    status = "ok" if digest_loaded else "no_digest"
    return BenchmarkResult(
        variant=variant.label,
        matrix=matrix_name,
        model=variant.model,
        temperature=variant.temperature,
        thinking_budget=variant.thinking_budget,
        thinking_level=variant.thinking_level,
        config_path=str(config_path),
        digest_loaded=digest_loaded,
        status=status,
    )


def run_matrix(
    matrix_name: str,
    cache: InsightCache,
    output_dir: Path,
) -> list[BenchmarkResult]:
    """Run all variants in a named matrix."""
    variants = MATRICES[matrix_name]
    results: list[BenchmarkResult] = []

    matrix_dir = output_dir / matrix_name
    matrix_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 72}")
    print(f"  Matrix: {matrix_name}  ({len(variants)} variants)")
    print(f"  Agent:  {MATRIX_AGENT[matrix_name]}")
    print(f"{'=' * 72}")

    for i, variant in enumerate(variants, 1):
        print(f"\n  [{i}/{len(variants)}] {variant.label}")
        print(f"    model={variant.model}  temp={variant.temperature}  "
              f"budget={variant.thinking_budget}  level={variant.thinking_level}")
        try:
            result = run_variant(variant, matrix_name, cache, matrix_dir)
            print(f"    -> {result.status}  digest_loaded={result.digest_loaded}")
            results.append(result)
        except Exception as exc:
            print(f"    -> ERROR: {exc}")
            results.append(BenchmarkResult(
                variant=variant.label,
                matrix=matrix_name,
                model=variant.model,
                temperature=variant.temperature,
                thinking_budget=variant.thinking_budget,
                thinking_level=variant.thinking_level,
                config_path="",
                digest_loaded=False,
                status="error",
                error=str(exc),
            ))

    return results


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------


def print_summary(results: list[BenchmarkResult]) -> None:
    """Print a formatted summary table of all benchmark results."""
    if not results:
        print("\nNo results to summarize.")
        return

    # Column widths
    lbl_w = max(len(r.variant) for r in results) + 2
    mdl_w = max(len(r.model) for r in results) + 2

    header = (
        f"{'Variant':<{lbl_w}} "
        f"{'Matrix':<12} "
        f"{'Model':<{mdl_w}} "
        f"{'Temp':>5} "
        f"{'Budget':>7} "
        f"{'Level':<8} "
        f"{'Digest':>6} "
        f"{'Status':<10}"
    )
    sep = "-" * len(header)

    print(f"\n{sep}")
    print("  BENCHMARK SUMMARY")
    print(sep)
    print(header)
    print(sep)

    for r in results:
        budget_str = str(r.thinking_budget) if r.thinking_budget is not None else "-"
        level_str = r.thinking_level if r.thinking_level else "-"
        digest_str = "yes" if r.digest_loaded else "NO"
        print(
            f"{r.variant:<{lbl_w}} "
            f"{r.matrix:<12} "
            f"{r.model:<{mdl_w}} "
            f"{r.temperature:>5.2f} "
            f"{budget_str:>7} "
            f"{level_str:<8} "
            f"{digest_str:>6} "
            f"{r.status:<10}"
        )

    print(sep)
    ok = sum(1 for r in results if r.status == "ok")
    no_digest = sum(1 for r in results if r.status == "no_digest")
    err = sum(1 for r in results if r.status == "error")
    print(f"  Total: {len(results)}  |  OK: {ok}  |  No digest: {no_digest}  |  Errors: {err}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark executive brief generation across model/settings combinations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run just the brief matrix
  python scripts/model_benchmark.py --cache-dir outputs/latest/.cache --matrix brief

  # Run all matrices
  python scripts/model_benchmark.py --cache-dir outputs/latest/.cache --matrix all

  # Custom output directory
  python scripts/model_benchmark.py --cache-dir outputs/latest/.cache --matrix narrative --output-dir /tmp/bench
""",
    )
    parser.add_argument(
        "--cache-dir",
        required=True,
        help="Path to the .cache directory containing cached insight cards and digest.",
    )
    parser.add_argument(
        "--matrix",
        required=True,
        choices=["brief", "narrative", "synthesis", "all"],
        help="Which test matrix to run.",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_results",
        help="Directory for benchmark output files (default: benchmark_results/).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Resolve paths
    cache_dir = Path(args.cache_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # The InsightCache expects the *parent* of .cache as output_dir.
    # If the user passed the .cache dir itself, go up one level.
    if cache_dir.name == ".cache":
        cache = InsightCache(str(cache_dir.parent))
    else:
        cache = InsightCache(str(cache_dir))

    # Determine which matrices to run
    if args.matrix == "all":
        matrix_names = list(MATRICES.keys())
    else:
        matrix_names = [args.matrix]

    print(f"Cache directory : {cache.cache_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Matrices        : {', '.join(matrix_names)}")

    summary = cache.get_cache_summary()
    print(f"Cached digest   : {'yes' if summary['has_digest'] else 'NO'}")
    print(f"Cached metrics  : {', '.join(summary['metrics']) or 'none'}")

    # Run
    all_results: list[BenchmarkResult] = []
    for name in matrix_names:
        results = run_matrix(name, cache, output_dir)
        all_results.extend(results)

    # Save combined results
    combined_path = output_dir / "benchmark_results.json"
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in all_results], f, indent=2, default=str)

    print_summary(all_results)
    print(f"Full results saved to: {combined_path}")


if __name__ == "__main__":
    main()
