# Code Review — 2026-03-17 17:04 UTC (Arbiter Audit)

**Commit range:** `fb355be..cf881d8` (last 10 commits)  
**Scope:** 7 source files changed + 9 doc files, ~1990 insertions  
**Previous audit:** 2026-03-13 05:50 UTC (979ed10)

---

## Critical (must fix before merge)

_None._ No new data integrity or pipeline-breaking issues detected.

---

## Warning (fix soon)

### 1. Unused imports — 60+ across codebase (PERSISTENT)

This was flagged in the previous two audits and remains unaddressed. Key offenders:

**High-priority (real library imports wasting load time):**
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_new_lost_same_store.py:29` — `import numpy` (unused)
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_outlier_impact.py:26` — `from scipy import stats` (unused, heavy import)
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/detect_mad_outliers.py:27` — `from io import StringIO` (unused)
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/detect_change_points.py:30` — `from io import StringIO` (unused)
- `data_analyst_agent/semantic/quality.py:2` — `import numpy` (unused)

**Medium-priority (typing imports — no runtime cost but code noise):**
- `data_analyst_agent/config.py:19` — `Optional`
- `data_analyst_agent/cli_validator.py:9` — `Optional`
- `data_analyst_agent/tools/should_fetch_supplementary_data.py:17` — `Dict`
- `data_analyst_agent/sub_agents/dynamic_parallel_agent.py:1` — `List`, `Any`
- `data_analyst_agent/sub_agents/dynamic_parallel_agent.py:8` — `import time`
- `data_analyst_agent/utils/phase_logger.py:39` — `List`
- `data_analyst_agent/semantic/lag_utils.py:1` — `Optional`
- `data_analyst_agent/semantic/policies.py:2` — `List`, `Dict`, `Union`
- `data_analyst_agent/semantic/quality.py:3` — `Dict`, `Any`, `Optional`
- `data_analyst_agent/semantic/quality.py:5` — `QualityGateError`
- `data_analyst_agent/semantic/models.py:6` — `ContractValidationError`
- Multiple `from __future__ import annotations` in files that don't use any PEP 604+ syntax

**Recommendation:** Run `ruff check --select F401 data_analyst_agent/` to auto-detect, then `ruff check --select F401 --fix` to auto-remove. One commit, done.

---

### 2. Prompt token bloat — 2 of 3 files over threshold

| File | Size | Status |
|------|------|--------|
| `config/prompts/executive_brief.md` | 4,618 chars | ⚠️ **Over 3,000 threshold** |
| `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py` | 6,022 chars | ⚠️ **Over 3,000 threshold (2x)** |
| `data_analyst_agent/sub_agents/narrative_agent/prompt.py` | 2,791 chars | ✅ Under threshold |

**Note:** The previous audit (05:50 UTC) flagged this as "partially resolved." `narrative_agent/prompt.py` dropped below threshold (good), but `report_synthesis_agent/prompt.py` remains at 6K and `executive_brief.md` at 4.6K. These prompts fire every pipeline run — token cost adds up.

**Recommendation:** Extract examples from `report_synthesis_agent/prompt.py` into few-shot config. For `executive_brief.md`, the forbidden-title validation added in cf881d8 may allow removing the lengthy "DO NOT" examples from the prompt itself.

---

### 3. Hardcoded trade_data references — partially documented, not yet resolved

**Already documented (validation_data_loader.py):** The TODO block added in the last cycle correctly identifies the hardcoded column mappings at lines 144-148, 155, 199. Good documentation, but no code fix yet.

**Hardcoded card tags in report formatting:**
- `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/sections/insight_cards.py:35` — hardcoded tag set `{"regional_distribution", "hierarchy", "regional_analysis"}` for section grouping. These should come from the contract's dimension hierarchy.
- `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/formatting.py:18` — `"regional_analysis"` in section ordering

**Hardcoded examples in executive_brief_agent prompts:**
- `agent.py:1211` — `"The West region contributed $31.66M..."` — trade_data-specific example baked into prompt. If this agent runs against a different dataset, the example misleads the LLM.
- `agent.py:1203, 1479` — `"multiple regions"` in anti-pattern examples (less critical, but still dataset-flavored)

**Heuristic dimension keywords (acceptable with contract fallback):**
- `narrative_agent/tools/generate_narrative_summary.py:125` — `_generic_key_priority()` uses keyword heuristics ("region", "country", etc.) BUT correctly falls through to contract-driven priority first. This is **fine** as a fallback.

---

## ADK Compliance

### Good patterns observed in recent commits:
- ✅ `max_output_tokens` reduced from 4096→2048 in narrative + synthesis agents (dae6111) — matches actual output size
- ✅ Forbidden section title validation added BEFORE normalization (cf881d8) — prevents auto-fix masking LLM errors
- ✅ Fallback detection improved with substantive content checks (0f4cc4d)
- ✅ Contract-driven dimension prioritization added to narrative agent (0f4cc4d)

### No issues:
- Agent boundaries handle errors correctly (retry → fallback pattern)
- State key isolation looks clean in the diff
- No new global variables introduced

---

## Observations

1. **Documentation-heavy cycle.** 9 of 16 changed files are docs/session summaries. The code changes (7 files) are focused and surgical — good discipline.

2. **Retry+fallback pattern maturing.** The executive_brief_agent now has three validation layers: (a) forbidden title check, (b) section normalization, (c) fallback content detection. Well-structured defense-in-depth.

3. **Unused imports are becoming technical debt.** Third consecutive audit flagging this. The `scipy.stats` and `numpy` unused imports in statistical tools suggest copy-paste scaffolding that was never cleaned up. This is a 5-minute fix with `ruff`.

4. **Token efficiency improving.** `max_output_tokens` reductions and narrative prompt trimming show active cost awareness. Next target should be `report_synthesis_agent/prompt.py` at 6K chars.

---

## Action Items for Dev Agent

| Priority | Item | Effort |
|----------|------|--------|
| P1 | Run `ruff check --select F401 --fix` to clear unused imports | 5 min |
| P2 | Trim `report_synthesis_agent/prompt.py` — extract examples to config | 30 min |
| P2 | Replace hardcoded card tags (`regional_analysis` etc.) with contract-driven tags | 30 min |
| P3 | Parameterize executive_brief example text per dataset | 15 min |
| P3 | Trim `executive_brief.md` prompt now that validation catches bad titles | 15 min |
