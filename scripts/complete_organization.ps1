# Complete Code Organization Script (PowerShell)
# Run this after closing all files in your editor

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "P&L Analyst - Code Organization Script" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Change to project directory
Set-Location "C:\Streamlit\development\pl_analyst"

Write-Host "Step 1: Moving markdown files to archive..." -ForegroundColor Yellow
Write-Host "-------------------------------------------" -ForegroundColor Yellow

$markdownFiles = @(
    "HIERARCHICAL_IMPLEMENTATION.md",
    "HIERARCHICAL_DRILL_DOWN_COMPLETE.md",
    "ROOT_CAUSE_ANALYSIS.md",
    "TROUBLESHOOTING_HANG.md",
    "EFFICIENCY_REFACTORING_COMPLETE.md",
    "STATISTICAL_ANALYSIS_ASSESSMENT.md",
    "QUICKSTART_FIXES.md",
    "ENHANCEMENT_COMPLETION_SUMMARY.md",
    "TEST_EXECUTION_SUMMARY.md",
    "TEST_MODE_README.md",
    "PRODUCTION_READINESS_SUMMARY.md"
)

foreach ($file in $markdownFiles) {
    if (Test-Path $file) {
        Move-Item -Path $file -Destination "archive\" -Force
        Write-Host "✓ Moved $file" -ForegroundColor Green
    } else {
        Write-Host "- $file not found (may be already moved)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Step 2: Moving remaining debug script..." -ForegroundColor Yellow
Write-Host "-------------------------------------------" -ForegroundColor Yellow

if (Test-Path "diagnose_hang.py") {
    Move-Item -Path "diagnose_hang.py" -Destination "archive\" -Force
    Write-Host "✓ Moved diagnose_hang.py" -ForegroundColor Green
} else {
    Write-Host "- diagnose_hang.py not found" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Step 3: Moving unit test files..." -ForegroundColor Yellow
Write-Host "-------------------------------------------" -ForegroundColor Yellow

$unitTests = @(
    "test_validation_agent_isolated.py",
    "test_advanced_stats.py",
    "test_advanced_stats_direct.py",
    "test_persistence_direct.py"
)

foreach ($file in $unitTests) {
    if (Test-Path $file) {
        Move-Item -Path $file -Destination "tests\unit\" -Force
        Write-Host "✓ Moved $file" -ForegroundColor Green
    } else {
        Write-Host "- $file not found" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Step 4: Moving integration test files..." -ForegroundColor Yellow
Write-Host "-------------------------------------------" -ForegroundColor Yellow

$integrationTests = @(
    "test_sequential_context.py",
    "test_loop_continuation.py",
    "test_advanced_integration.py"
)

foreach ($file in $integrationTests) {
    if (Test-Path $file) {
        Move-Item -Path $file -Destination "tests\integration\" -Force
        Write-Host "✓ Moved $file" -ForegroundColor Green
    } else {
        Write-Host "- $file not found" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Step 5: Moving E2E test files..." -ForegroundColor Yellow
Write-Host "-------------------------------------------" -ForegroundColor Yellow

$e2eTests = @(
    "test_with_csv.py",
    "test_full_workflow_advanced.py",
    "test_efficient_workflow.py"
)

foreach ($file in $e2eTests) {
    if (Test-Path $file) {
        Move-Item -Path $file -Destination "tests\e2e\" -Force
        Write-Host "✓ Moved $file" -ForegroundColor Green
    } else {
        Write-Host "- $file not found" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "File organization complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Edit .gitignore manually (see COMPLETION_STATUS.md)"
Write-Host "2. Edit requirements.txt manually (see COMPLETION_STATUS.md)"
Write-Host "3. Edit README.md manually (see COMPLETION_STATUS.md)"
Write-Host "4. Install pytest: pip install pytest pytest-cov"
Write-Host "5. Run tests: pytest tests/ -v"
Write-Host ""
Write-Host "See COMPLETION_STATUS.md for detailed instructions." -ForegroundColor Cyan
Write-Host ""
