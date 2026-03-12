# Code Review — Reviewer Audit 2026-03-12T18:16Z

**Commit range:** `e3062c9..7ff5c67` (last 10 commits)
**Scope:** 24 files changed, +12,481 / -74 lines
**Reviewer:** Arbiter (automated audit)

---

## Critical (must fix before merge)

### 1. `config/prompts/executive_brief.md` — 18,785 chars (6.3× over budget)

The executive brief prompt is **18,785 characters** — well above the 3,000-char efficiency threshold. This prompt is injected into every LLM call for executive brief generation, burning significant tokens on every run. A `executive_brief_v2.md` exists at 5,771 chars (~69% reduction) but the original is still the active file.

**Fix:** Replace `executive_brief.md` with the v2 content, or update the loader to reference `executive_brief_v2.md`. Delete the bloated original.

### 2. `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py` — 6,022 chars (2× over budget)

At 6,022 characters this prompt exceeds the 3,000-char threshold. Review for redundant instructions, verbose examples, or sections that could be moved to contract metadata.

**Fix:** Audit for duplicated instructions and trim to ≤3,000 chars.

---

## Warning (fix soon)

### 3. `executive_brief_agent/agent.py` — Duplicated section title enforcement blocks

The section title enforcement logic (lines ~1047-1070 and ~1309-1330) is copy-pasted between network-level and scoped brief generation. Both blocks construct identical `FORBIDDEN SECTION TITLES` lists and `VALIDATION PROCESS` descriptions as string literals.

**Fix:** Extract into a shared helper function (e.g., `_build_section_enforcement(section_contract)`) to eliminate duplication and reduce drift risk.

### 4. Hardcoded tag strings in report formatting

- `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/formatting.py:18` — hardcoded `"regional_analysis"` tag
- `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/sections/insight_cards.py:35` — hardcoded `{"regional_distribution", "hierarchy", "regional_analysis"}` tag set

These tag strings assume a trade-data domain. If the pipeline processes a non-regional dataset (e.g., Tableau Superstore with "Category" as primary dimension), these tags will never match, silently skipping the regional narrative section.

**Fix:** Drive card tag → section mapping from the contract's dimension definitions, or at minimum make the tag set configurable.

### 5. `narrative_agent/tools/generate_narrative_summary.py:101` — Hardcoded geo-keyword heuristic

```python
if any(token in kl for token in ("region", "country", "market", "geo")):
```

This keyword-matching heuristic determines narrative formatting behavior based on hardcoded strings rather than reading dimension types from the contract. Works for trade data but will misfire on datasets where "region" means something else or miss geographic dimensions with non-matching names.

**Fix:** Check `contract.dimensions[dim].type == "geographic"` (or similar contract metadata) instead of keyword matching.

---

## Unused Imports (126 total)

**Impact:** Dead imports add cognitive noise, slow module loading (especially heavy ones like `numpy`, `pandas`, `scipy.stats`), and trigger linter warnings. Key offenders:

| Category | Count | Examples |
|---|---|---|
| `from __future__ import annotations` (unused) | ~45 | Scattered across utils/, stat tools, report sections |
| `typing` imports (`Dict`, `Any`, `List`, `Optional`) | ~35 | stat tools, alert scoring, semantic layer |
| Heavy library imports | 5 | `numpy` (×3), `pandas` (×2), `scipy.stats` (×1) |
| Functional dead imports | ~10 | `os`, `time`, `StringIO`, `CSS from weasyprint` |
| Named import shadowing | 2 | `agent.py:79-80` imports two different `root_agent` |

**Worst offenders (runtime cost):**
- `statistical_insights_agent/tools/compute_new_lost_same_store.py:29` — `import numpy` (unused)
- `hierarchy_variance_agent/tools/compute_pvm_decomposition.py:28` — `import pandas` (unused)
- `hierarchy_variance_agent/tools/compute_mix_shift_analysis.py:27` — `import pandas` (unused)
- `sub_agents/report_synthesis_agent/tools/export_pdf_report.py:44` — `CSS from weasyprint` (unused, heavy C extension)
- `sub_agents/report_synthesis_agent/prompt.py:26` — `import os` (unused)

**Fix:** Run `ruff check --select F401 data_analyst_agent/` to auto-detect and `ruff check --fix --select F401` to auto-remove. Or add `# noqa: F401` for intentional re-exports.

**Note on `from __future__ import annotations`:** Many of these are technically harmless (PEP 563 future import), but in files that don't use any type annotations, they're dead weight. Low priority to remove but contributes to import noise.

---

## ADK Compliance

### `agent.py:79-80` — Dual `root_agent` import shadowing

```python
from .sub_agents.statistical_insights_agent.agent import root_agent  # line 79
from .sub_agents.hierarchical_analysis_agent import root_agent       # line 80
```

Line 80 shadows line 79. If both are intentionally different agents being registered, they need distinct names. If one is dead, remove it.

---

## Observations

### Commit Quality
The last 10 commits are well-structured: clear prefixes (`feat:`, `fix:`, `docs:`, `cleanup:`), focused changes. The Tableau Superstore dataset was added and then cleaned up (commits `770eeb8` → `ac719d1`), which is good hygiene.

### Documentation Density
4 of 10 commits are docs-only (`docs:` prefix). The doc files add +530 lines of markdown. Consider whether session summaries (`NIGHT_SHIFT_SUMMARY.md`, `IMPROVEMENTS_2026-03-12.md`) should live in `docs/` or be ephemeral. They'll accumulate fast.

### New `contract_cache.py` Utility
Good addition — caching contract parsing avoids repeated YAML deserialization. Verify it invalidates on file change (mtime or hash check) to prevent stale contracts in dev.

### Prompt Engineering Pattern
The section title enforcement block in `executive_brief_agent/agent.py` is a solid approach to LLM output structure compliance. The "forbidden titles" list with explicit alternatives is good prompt engineering. However, embedding it as a string literal means it drifts from `NETWORK_SECTION_CONTRACT` if the contract changes.

### Token Budget Summary
| File | Size | Status |
|---|---|---|
| `config/prompts/executive_brief.md` | 18,785 chars | 🔴 6.3× over |
| `report_synthesis_agent/prompt.py` | 6,022 chars | 🟡 2× over |
| `narrative_agent/prompt.py` | 1,853 chars | ✅ Under budget |
| `executive_brief_v2.md` | 5,771 chars | 🟡 1.9× over (improved) |

---

*Generated by Arbiter (reviewer agent) — 2026-03-12T18:16Z*
