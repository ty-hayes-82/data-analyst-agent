#!/bin/bash
# Comprehensive E2E testing for ops_metrics_weekly dataset

set -e
cd /data/data-analyst-agent

echo "============================================================"
echo "OPS METRICS WEEKLY - COMPREHENSIVE E2E TEST SUITE"
echo "============================================================"
echo ""

export ACTIVE_DATASET=ops_metrics_weekly

# Test 1: Anomaly Detection
echo "TEST 1: Anomaly Detection (Basic Validation)"
echo "------------------------------------------------------------"
DATA_ANALYST_FOCUS=anomaly_detection \
python -m data_analyst_agent \
    --dataset ops_metrics_weekly \
    --metrics "ttl_rev_amt,ordr_cnt" 2>&1 | grep -E "(rows in|BRIEF|Process exited)" | tail -5

echo ""
echo "✅ Test 1 Complete"
echo ""

# Test 2: Recent Weekly Trends
echo "TEST 2: Recent Weekly Trends (Time-Series Focus)"
echo "------------------------------------------------------------"
DATA_ANALYST_FOCUS=recent_weekly_trends \
python -m data_analyst_agent \
    --dataset ops_metrics_weekly \
    --metrics "ttl_rev_amt,truck_count,ordr_miles" 2>&1 | grep -E "(rows in|BRIEF|Process exited)" | tail -5

echo ""
echo "✅ Test 2 Complete"
echo ""

# Test 3: YoY Comparison
echo "TEST 3: YoY Comparison (Annual Trends)"
echo "------------------------------------------------------------"
DATA_ANALYST_FOCUS=yoy_comparison \
python -m data_analyst_agent \
    --dataset ops_metrics_weekly \
    --metrics "ttl_rev_amt" 2>&1 | grep -E "(rows in|BRIEF|Process exited)" | tail -5

echo ""
echo "✅ Test 3 Complete"
echo ""

# Test 4: Seasonal Patterns
echo "TEST 4: Seasonal Patterns (Cyclical Analysis)"
echo "------------------------------------------------------------"
DATA_ANALYST_FOCUS=seasonal_patterns \
python -m data_analyst_agent \
    --dataset ops_metrics_weekly \
    --metrics "ordr_cnt" 2>&1 | grep -E "(rows in|BRIEF|Process exited)" | tail -5

echo ""
echo "✅ Test 4 Complete"
echo ""

# Test 5: Multi-Focus with Custom Instructions
echo "TEST 5: Multi-Focus Analysis"
echo "------------------------------------------------------------"
DATA_ANALYST_FOCUS=anomaly_detection,yoy_comparison,recent_weekly_trends \
DATA_ANALYST_CUSTOM_FOCUS="Identify operational bottlenecks and efficiency drops across all business lines." \
python -m data_analyst_agent \
    --dataset ops_metrics_weekly \
    --metrics "ttl_rev_amt,ordr_miles,truck_count" 2>&1 | grep -E "(rows in|BRIEF|Process exited)" | tail -5

echo ""
echo "✅ Test 5 Complete"
echo ""

# Test 6: Hierarchical Drill-Down
echo "TEST 6: Hierarchical Drill-Down (Dimension Analysis)"
echo "------------------------------------------------------------"
python -m data_analyst_agent \
    --dataset ops_metrics_weekly \
    --metrics "ttl_rev_amt" \
    --dimension "gl_rgn_nm" 2>&1 | grep -E "(rows in|BRIEF|Level|Process exited)" | tail -10

echo ""
echo "✅ Test 6 Complete"
echo ""

echo "============================================================"
echo "ALL TESTS COMPLETE"
echo "============================================================"
