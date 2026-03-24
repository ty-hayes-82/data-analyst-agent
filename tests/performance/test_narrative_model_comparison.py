"""Benchmark harness for narrative model tiers.

Run manually with:
    RUN_MODEL_BENCHMARKS=1 pytest tests/performance/test_narrative_model_comparison.py -m requires_llm -s
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from google.genai import Client, types

from config.model_loader import _load_agent_models_config


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "experiments"
    / "fixtures"
    / "narrative_input.json"
)
_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2]
    / "outputs"
    / "debug"
    / "model_benchmarks"
)


def _enabled() -> bool:
    import os

    return os.getenv("RUN_MODEL_BENCHMARKS", "").strip().lower() in {"1", "true", "yes", "on"}


def _tiers_to_compare() -> list[str]:
    cfg = _load_agent_models_config()
    available = set((cfg.get("model_tiers") or {}).keys())
    ordered = ["flash_2_5", "standard", "fast", "brief", "ultra"]
    return [tier for tier in ordered if tier in available]


def _model_for_tier(tier_name: str) -> str:
    cfg = _load_agent_models_config()
    tier = (cfg.get("model_tiers") or {}).get(tier_name, {})
    return str(tier.get("model", "")).strip()


@pytest.mark.performance
@pytest.mark.slow
@pytest.mark.requires_llm
@pytest.mark.parametrize("tier_name", _tiers_to_compare())
def test_narrative_model_latency_smoke(tier_name: str):
    if not _enabled():
        pytest.skip("Set RUN_MODEL_BENCHMARKS=1 to run model benchmarks")

    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    prompt = json.dumps(fixture, separators=(",", ":"), ensure_ascii=False)
    model_name = _model_for_tier(tier_name)
    if not model_name:
        pytest.skip(f"No model configured for tier={tier_name}")

    client = Client(vertexai=False)
    start = time.perf_counter()
    response = client.models.generate_content(
        model=model_name,
        contents=(
            "You are benchmarking narrative generation quality.\n"
            "Return ONLY a compact JSON object with keys: "
            "narrative_summary, insight_cards, recommended_actions.\n"
            f"INPUT_JSON:{prompt}"
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
            max_output_tokens=1024,
        ),
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    output_text = getattr(response, "text", "") or ""
    assert output_text.strip(), f"empty output for tier={tier_name}"

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result_path = _OUTPUT_DIR / f"narrative_{tier_name}.json"
    result_path.write_text(
        json.dumps(
            {
                "tier": tier_name,
                "model": model_name,
                "latency_ms": elapsed_ms,
                "response_chars": len(output_text),
                "response_preview": output_text[:400],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
