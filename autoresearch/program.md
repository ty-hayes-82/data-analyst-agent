# autoresearch: Data Analyst Agent Pipeline Optimization

Adapted from [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) pattern.

## What this does

An autonomous loop that continuously improves the quality of executive briefs produced by the data-analyst-agent pipeline. Instead of optimizing ML training code, we optimize **prompts, configs, and agent parameters** — scored by a deterministic + LLM critic rubric (Brief Quality Score, 0-100).

## How it works

```
LOOP:
  1. Pick a prompt/config file to modify
  2. Use LLM to propose ONE small, targeted change
  3. Git commit the change
  4. Run pipeline on 2 evaluation datasets (Global Superstore + Iowa Liquor)
  5. Score the output (Tier 1: structural checks + Tier 2: LLM critic)
  6. IF score improved: KEEP (advance the branch)
     ELSE: DISCARD (git reset --hard)
  7. Log results to results.tsv
  8. Repeat until budget exhausted or max iterations reached
```

## Scoring rubric (BQS 0-100)

**Tier 1 (0-50, deterministic):** JSON validity, section completeness, numeric density, insight card count, evidence grounding, contract compliance, no stub content.

**Tier 2 (0-50, LLM critic):** Actionability, causal depth, data specificity, narrative coherence, completeness.

## What gets modified

Priority 1 (prompts):
- `config/prompts/executive_brief_ceo.md` — CEO brief generation
- `config/prompts/report_synthesis.md` — report synthesis
- `data_analyst_agent/sub_agents/narrative_agent/prompt.py` — narrative instruction

Priority 2 (config): drill depth, materiality thresholds
Priority 3 (params): NARRATIVE_MAX_TOP_DRIVERS, NARRATIVE_MAX_ANOMALIES, etc.

## What is IMMUTABLE

- Dataset contracts and CSV data files
- The scoring function (`autoresearch/evaluate.py`)
- Core ADK framework code
- The `autoresearch/` directory itself

## Running

```bash
# Baseline + 10 experiments:
python autoresearch/loop.py --max-iterations 10 --budget 1.0

# Full overnight run:
python autoresearch/loop.py --max-iterations 50 --budget 5.0
```

## Current optimization focus

- Improve **actionability** of leadership recommendations (be specific, name entities)
- Improve **causal depth** (explain WHY, not just WHAT)
- Maintain **data specificity** (exact numbers, not vague qualifiers)
- Keep brief structure tight (no bloat, no redundancy)

## Cost

~$0.09 per experiment. Budget of $2 allows ~22 experiments per session.
