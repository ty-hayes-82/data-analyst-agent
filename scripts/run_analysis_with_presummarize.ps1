# Run analysis with pre-summarization enabled.
# Pre-summarization sends each of 5 prompt components through a fast LLM before
# the main synthesis, reducing injection size (~22K -> ~2.5K chars).
# Benchmark first: python scripts/benchmark_presummarize.py
#
# Execute from pl_analyst dir: .\scripts\run_analysis_with_presummarize.ps1
# Or: powershell -ExecutionPolicy Bypass -File scripts\run_analysis_with_presummarize.ps1

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Push-Location $projectRoot
try {
    $env:PYTHONPATH = $projectRoot
    $env:REPORT_SYNTHESIS_PRE_SUMMARIZE = "1"
    $env:REPORT_SYNTHESIS_SUMMARIZER_MODEL = "gemini-3-flash-preview"
    # Use the default operational profile (core + operational analyses)
    # Available profiles: minimal, lean, full, custom
    $env:STATISTICAL_PROFILE = "lean"

    python -m data_analyst_agent --dataset validation_ops --metrics "LRPM"
}
finally {
    Pop-Location
}
