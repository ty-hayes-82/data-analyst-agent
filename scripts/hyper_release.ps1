# Release Hyper locks: stop Python runs for this repo and optional Tableau Desktop.
# Run from repo root:  powershell -ExecutionPolicy Bypass -File scripts/hyper_release.ps1

$ErrorActionPreference = "Continue"
$repoMarker = "data-analyst-agent"

Write-Host "Scanning for Python processes tied to $repoMarker ..."
$stopped = @()
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match '^python(\d+)?\.exe$' -and $_.CommandLine -and (
            $_.CommandLine -match [regex]::Escape($repoMarker) -or
            $_.CommandLine -match 'data_analyst_agent'
        )
    } |
    ForEach-Object {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            $stopped += $_.ProcessId
            Write-Host "  Stopped PID $($_.ProcessId)"
        } catch {
            Write-Host "  Could not stop PID $($_.ProcessId): $_"
        }
    }

if (-not $stopped.Count) {
    Write-Host "No matching Python processes."
}

Write-Host "Tableau Desktop (optional) ..."
$tbl = Get-Process -Name "tabprotoservice", "Tableau" -ErrorAction SilentlyContinue
if ($tbl) {
    Write-Host "  Found: $($tbl.ProcessName -join ', ') - close Tableau manually if Hyper stays locked."
} else {
    Write-Host "  No Tableau processes matched tabprotoservice/Tableau."
}

Write-Host "Done."
