# Model Benchmark Results

## Scope

- Narrative tier comparison harness: `tests/performance/test_narrative_model_comparison.py`
- Primary output directory: `outputs/debug/model_benchmarks/`

## How To Run

```bash
RUN_MODEL_BENCHMARKS=1 pytest tests/performance/test_narrative_model_comparison.py -m requires_llm -s
```

## Captured Metrics

- `latency_ms`
- `response_chars`
- `response_preview`

## Latest Run (2026-03-23)

| Tier | Model | Latency (ms) | Response chars |
|------|-------|--------------|----------------|
| `brief` | `gemini-3.1-flash-lite-preview` | `2569` | `1862` |
| `ultra` | `gemini-2.5-flash-lite` | `3334` | `3549` |
| `flash_2_5` | `gemini-2.5-flash` | `5701` | `1189` |
| `fast` | `gemini-3-flash-preview` | `6218` | `102` |
| `standard` | `gemini-3-flash-preview` | `6723` | `102` |

## Decision Log

- 2026-03-23: Latency smoke benchmark executed via `tests/performance/test_narrative_model_comparison.py` (5/5 passing).
- 2026-03-23: Default `narrative_agent` tier updated to `brief` in `config/agent_models.yaml` based on best observed latency and robust response length.
- Next validation step: run 9-metric end-to-end quality pass and compare generated insight cards/recommended actions before/after tier switch.
