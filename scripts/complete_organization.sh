#!/bin/bash
# Complete Code Organization Script
# Run this after closing all files in your editor

set -e  # Exit on error

echo "============================================"
echo "P&L Analyst - Code Organization Script"
echo "============================================"
echo ""

# Change to project directory
cd "/c/Streamlit/development/pl_analyst"

echo "Step 1: Moving markdown files to archive..."
echo "-------------------------------------------"
if [ -f "HIERARCHICAL_IMPLEMENTATION.md" ]; then
    mv HIERARCHICAL_IMPLEMENTATION.md archive/ && echo "✓ Moved HIERARCHICAL_IMPLEMENTATION.md"
fi
if [ -f "HIERARCHICAL_DRILL_DOWN_COMPLETE.md" ]; then
    mv HIERARCHICAL_DRILL_DOWN_COMPLETE.md archive/ && echo "✓ Moved HIERARCHICAL_DRILL_DOWN_COMPLETE.md"
fi
if [ -f "ROOT_CAUSE_ANALYSIS.md" ]; then
    mv ROOT_CAUSE_ANALYSIS.md archive/ && echo "✓ Moved ROOT_CAUSE_ANALYSIS.md"
fi
if [ -f "TROUBLESHOOTING_HANG.md" ]; then
    mv TROUBLESHOOTING_HANG.md archive/ && echo "✓ Moved TROUBLESHOOTING_HANG.md"
fi
if [ -f "EFFICIENCY_REFACTORING_COMPLETE.md" ]; then
    mv EFFICIENCY_REFACTORING_COMPLETE.md archive/ && echo "✓ Moved EFFICIENCY_REFACTORING_COMPLETE.md"
fi
if [ -f "STATISTICAL_ANALYSIS_ASSESSMENT.md" ]; then
    mv STATISTICAL_ANALYSIS_ASSESSMENT.md archive/ && echo "✓ Moved STATISTICAL_ANALYSIS_ASSESSMENT.md"
fi
if [ -f "QUICKSTART_FIXES.md" ]; then
    mv QUICKSTART_FIXES.md archive/ && echo "✓ Moved QUICKSTART_FIXES.md"
fi
if [ -f "ENHANCEMENT_COMPLETION_SUMMARY.md" ]; then
    mv ENHANCEMENT_COMPLETION_SUMMARY.md archive/ && echo "✓ Moved ENHANCEMENT_COMPLETION_SUMMARY.md"
fi
if [ -f "TEST_EXECUTION_SUMMARY.md" ]; then
    mv TEST_EXECUTION_SUMMARY.md archive/ && echo "✓ Moved TEST_EXECUTION_SUMMARY.md"
fi
if [ -f "TEST_MODE_README.md" ]; then
    mv TEST_MODE_README.md archive/ && echo "✓ Moved TEST_MODE_README.md"
fi
if [ -f "PRODUCTION_READINESS_SUMMARY.md" ]; then
    mv PRODUCTION_READINESS_SUMMARY.md archive/ && echo "✓ Moved PRODUCTION_READINESS_SUMMARY.md"
fi

echo ""
echo "Step 2: Moving remaining debug script..."
echo "-------------------------------------------"
if [ -f "diagnose_hang.py" ]; then
    mv diagnose_hang.py archive/ && echo "✓ Moved diagnose_hang.py"
fi

echo ""
echo "Step 3: Moving unit test files..."
echo "-------------------------------------------"
if [ -f "test_validation_agent_isolated.py" ]; then
    mv test_validation_agent_isolated.py tests/unit/ && echo "✓ Moved test_validation_agent_isolated.py"
fi
if [ -f "test_advanced_stats.py" ]; then
    mv test_advanced_stats.py tests/unit/ && echo "✓ Moved test_advanced_stats.py"
fi
if [ -f "test_advanced_stats_direct.py" ]; then
    mv test_advanced_stats_direct.py tests/unit/ && echo "✓ Moved test_advanced_stats_direct.py"
fi
if [ -f "test_persistence_direct.py" ]; then
    mv test_persistence_direct.py tests/unit/ && echo "✓ Moved test_persistence_direct.py"
fi

echo ""
echo "Step 4: Moving integration test files..."
echo "-------------------------------------------"
if [ -f "test_sequential_context.py" ]; then
    mv test_sequential_context.py tests/integration/ && echo "✓ Moved test_sequential_context.py"
fi
if [ -f "test_loop_continuation.py" ]; then
    mv test_loop_continuation.py tests/integration/ && echo "✓ Moved test_loop_continuation.py"
fi
if [ -f "test_advanced_integration.py" ]; then
    mv test_advanced_integration.py tests/integration/ && echo "✓ Moved test_advanced_integration.py"
fi

echo ""
echo "Step 5: Moving E2E test files..."
echo "-------------------------------------------"
if [ -f "test_with_csv.py" ]; then
    mv test_with_csv.py tests/e2e/ && echo "✓ Moved test_with_csv.py"
fi
if [ -f "test_full_workflow_advanced.py" ]; then
    mv test_full_workflow_advanced.py tests/e2e/ && echo "✓ Moved test_full_workflow_advanced.py"
fi
if [ -f "test_efficient_workflow.py" ]; then
    mv test_efficient_workflow.py tests/e2e/ && echo "✓ Moved test_efficient_workflow.py"
fi

echo ""
echo "============================================"
echo "File organization complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "1. Edit .gitignore manually (see COMPLETION_STATUS.md)"
echo "2. Edit requirements.txt manually (see COMPLETION_STATUS.md)"
echo "3. Edit README.md manually (see COMPLETION_STATUS.md)"
echo "4. Install pytest: pip install pytest pytest-cov"
echo "5. Run tests: pytest tests/ -v"
echo ""
echo "See COMPLETION_STATUS.md for detailed instructions."
echo ""
