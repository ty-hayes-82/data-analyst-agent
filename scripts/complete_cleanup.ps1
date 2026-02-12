# Complete Project Cleanup Script
# Run this after closing ALL files in your editor
#
# Usage: powershell.exe -ExecutionPolicy Bypass -File complete_cleanup.ps1

$ErrorActionPreference = "Stop"
$projectRoot = "C:\Streamlit\development\pl_analyst"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Project Cleanup Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Change to project directory
Set-Location $projectRoot

# ============================================================================
# 1. Move Markdown Files to Archive
# ============================================================================
Write-Host "[1/7] Moving markdown documentation files to archive..." -ForegroundColor Yellow

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
    "TEST_MODE_README.md"
)

$movedCount = 0
foreach ($file in $markdownFiles) {
    if (Test-Path $file) {
        try {
            Move-Item -Path $file -Destination "archive\" -Force
            Write-Host "  + Moved: $file" -ForegroundColor Green
            $movedCount++
        }
        catch {
            Write-Host "  - Failed to move: $file - $_" -ForegroundColor Red
        }
    }
    else {
        Write-Host "  - Not found: $file" -ForegroundColor Gray
    }
}
Write-Host "  Moved $movedCount markdown files" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# 2. Move Debug Scripts to Archive
# ============================================================================
Write-Host "[2/7] Moving debug scripts to archive..." -ForegroundColor Yellow

$debugScripts = @(
    "diagnose_hang.py",
    "debug_workflow.py",
    "apply_fix.py",
    "apply_restructure.py"
)

$movedCount = 0
foreach ($script in $debugScripts) {
    if (Test-Path $script) {
        if (Test-Path "archive\$script") {
            Remove-Item -Path $script -Force
            Write-Host "  + Removed duplicate: $script (already in archive)" -ForegroundColor Green
        }
        else {
            try {
                Move-Item -Path $script -Destination "archive\" -Force
                Write-Host "  + Moved: $script" -ForegroundColor Green
                $movedCount++
            }
            catch {
                Write-Host "  - Failed to move: $script - $_" -ForegroundColor Red
            }
        }
    }
    else {
        Write-Host "  - Not found: $script" -ForegroundColor Gray
    }
}
Write-Host "  Moved $movedCount debug scripts" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# 3. Move Test Files to tests/unit/
# ============================================================================
Write-Host "[3/7] Moving unit test files..." -ForegroundColor Yellow

$unitTests = @(
    "test_validation_agent_isolated.py",
    "test_advanced_stats.py",
    "test_advanced_stats_direct.py",
    "test_persistence_direct.py"
)

$movedCount = 0
foreach ($test in $unitTests) {
    if (Test-Path $test) {
        try {
            Move-Item -Path $test -Destination "tests\unit\" -Force
            Write-Host "  + Moved: $test" -ForegroundColor Green
            $movedCount++
        }
        catch {
            Write-Host "  - Failed to move: $test - $_" -ForegroundColor Red
        }
    }
    else {
        Write-Host "  - Not found: $test" -ForegroundColor Gray
    }
}
Write-Host "  Moved $movedCount unit test files" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# 4. Move Test Files to tests/integration/
# ============================================================================
Write-Host "[4/7] Moving integration test files..." -ForegroundColor Yellow

$integrationTests = @(
    "test_sequential_context.py",
    "test_loop_continuation.py",
    "test_advanced_integration.py"
)

$movedCount = 0
foreach ($test in $integrationTests) {
    if (Test-Path $test) {
        try {
            Move-Item -Path $test -Destination "tests\integration\" -Force
            Write-Host "  + Moved: $test" -ForegroundColor Green
            $movedCount++
        }
        catch {
            Write-Host "  - Failed to move: $test - $_" -ForegroundColor Red
        }
    }
    else {
        Write-Host "  - Not found: $test" -ForegroundColor Gray
    }
}
Write-Host "  Moved $movedCount integration test files" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# 5. Move Test Files to tests/e2e/
# ============================================================================
Write-Host "[5/7] Moving e2e test files..." -ForegroundColor Yellow

$e2eTests = @(
    "test_with_csv.py",
    "test_full_workflow_advanced.py",
    "test_efficient_workflow.py"
)

$movedCount = 0
foreach ($test in $e2eTests) {
    if (Test-Path $test) {
        try {
            Move-Item -Path $test -Destination "tests\e2e\" -Force
            Write-Host "  + Moved: $test" -ForegroundColor Green
            $movedCount++
        }
        catch {
            Write-Host "  - Failed to move: $test - $_" -ForegroundColor Red
        }
    }
    else {
        Write-Host "  - Not found: $test" -ForegroundColor Gray
    }
}
Write-Host "  Moved $movedCount e2e test files" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# 6. Update .gitignore
# ============================================================================
Write-Host "[6/7] Updating .gitignore..." -ForegroundColor Yellow

if (Test-Path ".gitignore") {
    try {
        $gitignoreLines = Get-Content -Path ".gitignore"
        $modified = $false
        $newLines = @()

        foreach ($line in $gitignoreLines) {
            $newLines += $line

            # Add .env.example after .env.template
            if ($line -eq "!.env.template" -and $gitignoreLines -notcontains "!.env.example") {
                $newLines += "!.env.example"
                $modified = $true
                Write-Host "  + Added: !.env.example" -ForegroundColor Green
            }

            # Add log files after hyperd.log
            if ($line -eq "hyperd.log" -and $gitignoreLines -notcontains "test_*.log") {
                $newLines += "test_*.log"
                $newLines += "full_output.log"
                $newLines += "agent_*.log"
                $newLines += "workflow_*.log"
                $modified = $true
                Write-Host "  + Added: log file patterns" -ForegroundColor Green
            }

            # Uncomment archive/
            if ($line -eq "# archive/") {
                $newLines[-1] = "archive/"
                $modified = $true
                Write-Host "  + Uncommented: archive/" -ForegroundColor Green
            }
        }

        if ($modified) {
            $newLines | Set-Content -Path ".gitignore"
            Write-Host "  + .gitignore updated successfully" -ForegroundColor Green
        }
        else {
            Write-Host "  - .gitignore already up to date" -ForegroundColor Gray
        }
    }
    catch {
        Write-Host "  - Failed to update .gitignore: $_" -ForegroundColor Red
    }
}
else {
    Write-Host "  - .gitignore not found" -ForegroundColor Red
}
Write-Host ""

# ============================================================================
# 7. Update requirements.txt
# ============================================================================
Write-Host "[7/7] Updating requirements.txt..." -ForegroundColor Yellow

if (Test-Path "requirements.txt") {
    try {
        $reqLines = Get-Content -Path "requirements.txt"
        $modified = $false

        for ($i = 0; $i -lt $reqLines.Count; $i++) {
            if ($reqLines[$i] -eq "# pytest>=7.4.0") {
                $reqLines[$i] = "pytest>=7.4.0"
                $modified = $true
                Write-Host "  + Enabled pytest in requirements.txt" -ForegroundColor Green
            }
        }

        # Add pytest-cov if not present
        if ($reqLines -notcontains "pytest-cov>=4.1.0") {
            $reqLines += "pytest-cov>=4.1.0"
            $modified = $true
            Write-Host "  + Added pytest-cov to requirements.txt" -ForegroundColor Green
        }

        if ($modified) {
            $reqLines | Set-Content -Path "requirements.txt"
        }
        else {
            Write-Host "  - requirements.txt already up to date" -ForegroundColor Gray
        }
    }
    catch {
        Write-Host "  - Failed to update requirements.txt: $_" -ForegroundColor Red
    }
}
else {
    Write-Host "  - requirements.txt not found" -ForegroundColor Red
}
Write-Host ""

# ============================================================================
# Summary
# ============================================================================
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Cleanup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Install test dependencies:" -ForegroundColor White
Write-Host "   pip install pytest pytest-cov" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Run tests to verify:" -ForegroundColor White
Write-Host "   set PL_ANALYST_TEST_MODE=true" -ForegroundColor Gray
Write-Host "   pytest tests/ -v" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Review MANUAL_CHANGES_REQUIRED.md for:" -ForegroundColor White
Write-Host "   - README.md updates (security notice)" -ForegroundColor Gray
Write-Host "   - Credential security (backup, remove, rotate)" -ForegroundColor Gray
Write-Host ""

# Keep window open
Write-Host "Press any key to exit..." -ForegroundColor Cyan
$null = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
