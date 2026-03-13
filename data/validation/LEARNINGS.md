# Code Review — 2026-03-13 05:50 UTC (Arbiter Audit)

**Commit range:** `dd843d0..dd5e477` (last 10 commits)  
**Scope:** 19 files changed, 1845 insertions, 428 deletions  
**Previous audit:** 05:15 UTC (1bed93f)

---

## ✅ Fixed Since Last Audit

### 1. Executive Brief Prompt Token Reduction ✅ (commit 1643033)
`config/prompts/executive_brief.md` reduced from ~8000 chars → 4618 chars (42% reduction). Good. Still over 3000 char threshold — see Warning #2.

### 2. Narrative Dimension Prioritization Now Contract-Driven ✅ (commit 0f4cc4d)
`generate_narrative_summary.py` — `_generic_key_priority()` now accepts `dimension_priority` dict from contract hierarchy. Falls back to heuristic patterns only when contract doesn't specify. Clean fix.

### 3. Executive Brief Fallback Detection Improved ✅ (commit 0f4cc4d)
`prompt_utils.py` — `_format_brief_with_fallback()` now checks for placeholder text in Key Findings body, not just line count. Prevents briefs with SECTION_FALLBACK_TEXT from passing as valid.

### 4. max_output_tokens Reduced ✅ (commit dae6111)
- `narrative_agent/agent.py`: 4096 → 2048 (typical output ~800-1200 tokens)
- `report_synthesis_agent/agent.py`: 4096 → 2048 (typical output ~600-800 tokens)
Good cost optimization. Both locations updated consistently.

### 5. Validation Data Loader Documentation ✅ (commit fb355be)
`validation_data_loader.py` now has clear docstring noting dataset-specific limitations and TODO for contract-driven validation config. Acknowledges the tech debt properly.

---

## Critical (must fix before merge)

*None identified in this commit range.* Previous critical issues (hardcoded fallbacks in ratio_metrics, data_prep, outlier_impact, validation_csv_fetcher, validation_data_loader) remain fixed.

---

## Warning (fix soon)

### 1. Unused Imports — 140+ across codebase (ELEVATED from previous audit)
**Status: Persists.** This was flagged as critical in the 05:15 UTC audit. Still not addressed.

**Highest priority (non-`annotations` imports that indicate dead code):**

| File | Import | Risk |
|------|--------|------|
| `agent.py:79-80` | `root_agent as statistical_insights_agent`, `root_agent as hierarchical_analysis_agent` | Dead agent references — possible broken wiring |
| `semantic/quality.py:2` | `numpy as np` | Unused heavy dependency |
| `semantic/models.py:6` | `ContractValidationError` | Dead error handling path |
| `hierarchy_variance_agent/tools/compute_mix_shift_analysis.py:27` | `pandas as pd` | Unused heavy dependency |
| `hierarchy_variance_agent/tools/compute_pvm_decomposition.py:28` | `pandas as pd` | Unused heavy dependency |
| `statistical_insights_agent/tools/compute_new_lost_same_store.py:29` | `numpy as np` | Unused heavy dependency |
| `report_synthesis_agent/prompt.py:26` | `os` | Dead env access |
| `report_synthesis_agent/tools/export_pdf_report.py:44` | `CSS` | Dead weasyprint dependency |
| `tableau_hyper_fetcher/fetcher.py:37` | `HyperConnectionManager` | Dead connection manager reference |
| `dynamic_parallel_agent.py:8` | `time` | Dead timing code |

**~60 `from __future__ import annotations` imports** — these are harmless PEP 563 forward refs, likely intentional. Low priority.

**~30 unused `typing` imports** (Any, Dict, List, Optional, etc.) — cleanup noise but not harmful.

**The 10 items above are real dead code signals.** Particularly `agent.py:79-80` — if those agent modules aren't being imported correctly, sub-agent wiring may be silently broken.

**Recommendation:** Run `ruff check --select F401 data_analyst_agent/` for authoritative unused import detection. My AST scan is heuristic.

### 2. Prompt Token Sizes Still Over Threshold

| File | Size | Status |
|------|------|--------|
| `config/prompts/executive_brief.md` | **4618 chars** | ⚠️ Over 3000 (was ~8000, reduced 42%) |
| `report_synthesis_agent/prompt.py` | **6022 chars** | ⚠️ Over 3000, unchanged |
| `narrative_agent/prompt.py` | **2791 chars** | ✅ Under threshold |

`report_synthesis_agent/prompt.py` at 6022 chars is the largest prompt file and was not touched in this commit range. Should be next target for optimization.

### 3. Hardcoded Tag Strings in Report Synthesis

`report_markdown/formatting.py:18` — `"regional_analysis"` hardcoded tag  
`report_markdown/sections/insight_cards.py:34-39` — `"regional_distribution"`, `"hierarchy"`, `"regional_analysis"` hardcoded tag set

These tags determine which insight cards get rendered in the "Regional Analysis" section. If a dataset uses geographic dimensions with different card tags, this section silently produces nothing. Should be contract-driven or at minimum use configurable tag sets.

### 4. Executive Brief Agent Example Text Contains Dataset-Specific Values

`executive_brief_agent/agent.py:1166` — `"West: $1.8M, South: $1.2M, Midwest: $800K"`  
`executive_brief_agent/agent.py:1176` — `"West region contributed $31.66M (32.6% of network variance), while the South added $28.40M"`

These are in prompt example/template strings showing the LLM what good output looks like. Not a data integrity risk, but creates bias toward trade_data naming conventions. For true dataset-agnostic operation, these examples should be generated from contract metadata.

---

## ADK Compliance

### ✅ Commit Quality
- All 10 commits follow conventional commit format (docs:, perf:, fix:, review:)
- Code changes are well-scoped — no mixed concerns per commit
- `max_output_tokens` changes applied consistently across both factory and direct instantiation paths

### ✅ State Management
- `_generic_key_priority()` contract-driven change correctly threads `dimension_priority` through without mutating shared state
- Fallback detection in `prompt_utils.py` reads from brief_data dict (immutable pattern) — no side effects

### ⚠️ agent.py Import Concern
Lines 79-80 import `root_agent` from both `statistical_insights_agent` and `hierarchical_analysis_agent` but the names appear unused in the AST scan. If these are side-effect imports (registering agents), they should have `# noqa: F401` comments. If they're dead, they're masking that these agents aren't wired into the pipeline.

---

## Observations

1. **Development velocity is high** — 10 commits in ~70 minutes, all docs or targeted fixes. The dev iterate loop is working well.

2. **Prompt optimization paid off** — 42% reduction on executive_brief.md is meaningful. report_synthesis_agent prompt.py should be next.

3. **The unused import debt is accumulating.** 140+ detected. Most are harmless `annotations` or typing imports, but ~10 are real dead code that could mask broken wiring. A single `ruff` pass would clear this in minutes.

4. **Contract-driven pattern is maturing** — the narrative dimension prioritization fix (0f4cc4d) is exactly the right approach. Same pattern should be applied to insight card tag matching (Warning #3) and prompt example generation (Warning #4).

5. **No test changes in this commit range.** The code fixes (fallback detection, dimension prioritization, token reduction) should have corresponding test updates. Risk of regression if behavior changes aren't covered.

---

## Scoreboard Delta

| Metric | Previous (05:15) | Current (05:50) | Δ |
|--------|-------------------|------------------|---|
| Unused imports | 140+ | 140+ | No change |
| Prompt chars (exec brief) | ~8000 | 4618 | -42% ✅ |
| Prompt chars (report synth) | 6022 | 6022 | No change |
| Hardcoded assumptions | 3 remaining | 3 remaining | No change |
| Open warnings | 4 | 4 | Stable |
| Critical issues | 0 | 0 | Clean |
