# Autoresearch: Autonomous Pipeline Optimization

Kick off or manage an autoresearch experiment session.

**Usage:** $ARGUMENTS (e.g., `start`, `start 10`, `score <output_dir>`, `status`)

## Commands

### `start [max_iterations]` (default: 10)
Start the autonomous optimization loop on the current autoresearch/* branch.

```bash
cd /data/data-analyst-agent
python3 autoresearch/loop.py --max-iterations <N> --budget 2.0
```

### `score <output_dir>`
Score a specific pipeline output directory.

```bash
cd /data/data-analyst-agent
python3 autoresearch/evaluate.py <output_dir> <dataset_name>
```

### `status`
Show current autoresearch state: branch, latest results, best score.

```bash
cd /data/data-analyst-agent
git branch --show-current
tail -5 autoresearch/results.tsv
```

## Rules
- Must be on an `autoresearch/*` branch
- Never modify files in `autoresearch/` during the loop
- The loop handles git commits and reverts automatically
- Check `autoresearch/results.tsv` for experiment history
