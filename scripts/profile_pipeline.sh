#!/usr/bin/env bash
# Profile pipeline timing for narrative_agent and report_synthesis_agent optimization
#
# Usage: ./scripts/profile_pipeline.sh [dataset] [metrics]
# Example: ./scripts/profile_pipeline.sh trade_data "trade_value_usd,volume_units"

set -e

DATASET="${1:-trade_data}"
METRICS="${2:-trade_value_usd,volume_units}"

echo "==================================="
echo "Pipeline Profiler"
echo "==================================="
echo "Dataset: $DATASET"
echo "Metrics: $METRICS"
echo "==================================="

# Ensure we're in the project root
cd "$(dirname "$0")/.."

# Run pipeline and capture timing output
ACTIVE_DATASET="$DATASET" python -m data_analyst_agent \
    --dataset "$DATASET" \
    --metrics "$METRICS" \
    2>&1 | tee /tmp/pipeline_profile.log

echo ""
echo "==================================="
echo "Timing Summary"
echo "==================================="

# Extract timing data from log
grep "\[TIMER\]" /tmp/pipeline_profile.log | grep "Finished" | sort -k7 -rn | head -20

echo ""
echo "==================================="
echo "Slowest Agents (Top 10)"
echo "==================================="
grep "\[TIMER\]" /tmp/pipeline_profile.log | grep "Finished" | \
    awk '{print $7, $5}' | sed 's/s$//' | sort -rn | head -10

echo ""
echo "Full timing log saved to: /tmp/pipeline_profile.log"
echo ""
echo "Next steps for optimization:"
echo "1. Review prompt length for slow agents"
echo "2. Check token usage in Gemini API calls"
echo "3. Consider caching intermediate results"
echo "4. Evaluate if parallel execution is possible"
