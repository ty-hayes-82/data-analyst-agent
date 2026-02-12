# Cleanup script to organize project files

# Define file lists
$markdownDocs = @(
    'HIERARCHICAL_IMPLEMENTATION.md',
    'HIERARCHICAL_DRILL_DOWN_COMPLETE.md',
    'ROOT_CAUSE_ANALYSIS.md',
    'TROUBLESHOOTING_HANG.md',
    'EFFICIENCY_REFACTORING_COMPLETE.md',
    'STATISTICAL_ANALYSIS_ASSESSMENT.md',
    'QUICKSTART_FIXES.md',
    'ENHANCEMENT_COMPLETION_SUMMARY.md',
    'TEST_EXECUTION_SUMMARY.md',
    'TEST_MODE_README.md',
    'COMPLETION_STATUS.md',
    'CLEANUP_INSTRUCTIONS.md',
    'CLEANUP_SUMMARY.md',
    'MANUAL_CHANGES_REQUIRED.md',
    'HOW_TO_COMPLETE.md',
    'README_ADDITIONS.txt',
    'README_UPDATES.md',
    'GITIGNORE_CHANGES.txt',
    'REQUIREMENTS_CHANGES.txt'
)

$testFiles = @(
    'test_advanced_integration.py',
    'test_advanced_stats.py',
    'test_advanced_stats_direct.py',
    'test_efficient_workflow.py',
    'test_full_workflow_advanced.py',
    'test_loop_continuation.py',
    'test_persistence_direct.py',
    'test_sequential_context.py',
    'test_validation_agent_isolated.py',
    'test_with_csv.py',
    'quick_tests.py',
    'quick_validate_test.py'
)

$utilityScripts = @(
    'debug_load_cache.py',
    'fix_markdown_tool.py',
    'fix_test_indent.py',
    'generate_markdown_report_FIXED.py'
)

$psScripts = @(
    'complete_cleanup.ps1',
    'complete_organization.ps1',
    'complete_organization.sh',
    'update_rate_limits.ps1'
)

$logFiles = @(
    'full_output.log',
    'full_test_output.log',
    'test_final.log',
    'test_output.log',
    'test_run_detailed.log',
    'test_run_output.log',
    'test_run_with_fix.log',
    'test_with_fix.log',
    'web_server.log'
)

Write-Host "`n=== Moving Markdown Docs to Archive ===`n"
foreach ($file in $markdownDocs) {
    if (Test-Path $file) {
        try {
            Move-Item -Path $file -Destination "archive\$file" -Force
            Write-Host "[OK] Moved: $file"
        } catch {
            Write-Host "[ERROR] Failed to move $file : $_"
        }
    } else {
        Write-Host "[SKIP] Not found: $file"
    }
}

Write-Host "`n=== Moving Test Files to tests/ ===`n"
foreach ($file in $testFiles) {
    if (Test-Path $file) {
        try {
            Move-Item -Path $file -Destination "tests\$file" -Force
            Write-Host "[OK] Moved: $file"
        } catch {
            Write-Host "[ERROR] Failed to move $file : $_"
        }
    } else {
        Write-Host "[SKIP] Not found: $file"
    }
}

Write-Host "`n=== Moving Utility Scripts to Archive ===`n"
foreach ($file in $utilityScripts) {
    if (Test-Path $file) {
        try {
            Move-Item -Path $file -Destination "archive\$file" -Force
            Write-Host "[OK] Moved: $file"
        } catch {
            Write-Host "[ERROR] Failed to move $file : $_"
        }
    } else {
        Write-Host "[SKIP] Not found: $file"
    }
}

Write-Host "`n=== Moving PowerShell Scripts to scripts/ ===`n"
foreach ($file in $psScripts) {
    if (Test-Path $file) {
        try {
            Move-Item -Path $file -Destination "scripts\$file" -Force
            Write-Host "[OK] Moved: $file"
        } catch {
            Write-Host "[ERROR] Failed to move $file : $_"
        }
    } else {
        Write-Host "[SKIP] Not found: $file"
    }
}

Write-Host "`n=== Deleting Log Files ===`n"
foreach ($file in $logFiles) {
    if (Test-Path $file) {
        try {
            Remove-Item -Path $file -Force
            Write-Host "[OK] Deleted: $file"
        } catch {
            Write-Host "[ERROR] Failed to delete $file : $_"
        }
    } else {
        Write-Host "[SKIP] Not found: $file"
    }
}

Write-Host "`n=== Deleting Empty/Unnecessary Files ===`n"
if (Test-Path 'nul') {
    try {
        Remove-Item -Path 'nul' -Force
        Write-Host "[OK] Deleted: nul"
    } catch {
        Write-Host "[ERROR] Failed to delete nul : $_"
    }
}

# Special handling for diagnose_hang.py if it wasn't moved yet
if (Test-Path 'diagnose_hang.py') {
    if (!(Test-Path 'archive\diagnose_hang.py')) {
        try {
            Move-Item -Path 'diagnose_hang.py' -Destination 'archive\diagnose_hang.py' -Force
            Write-Host "[OK] Moved: diagnose_hang.py"
        } catch {
            Write-Host "[ERROR] Failed to move diagnose_hang.py : $_"
        }
    } else {
        Write-Host "[INFO] diagnose_hang.py already exists in archive, deleting root copy"
        try {
            Remove-Item -Path 'diagnose_hang.py' -Force
            Write-Host "[OK] Deleted: diagnose_hang.py"
        } catch {
            Write-Host "[ERROR] Failed to delete diagnose_hang.py : $_"
        }
    }
}

Write-Host "`n=== Cleanup Complete! ===`n"
