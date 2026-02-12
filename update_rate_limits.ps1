# Update rate limit settings in .env file
# This fixes the hang issue by increasing the RPM limit

$envFile = Join-Path $PSScriptRoot ".env"

if (Test-Path $envFile) {
    Write-Host "Updating rate limits in .env file..." -ForegroundColor Yellow
    
    $content = Get-Content $envFile
    $updated = $false
    
    # Update RPM limit from 5 to 30
    $content = $content -replace 'GOOGLE_GENAI_RPM_LIMIT=5', 'GOOGLE_GENAI_RPM_LIMIT=30'
    
    $content | Set-Content $envFile
    
    Write-Host "Updated GOOGLE_GENAI_RPM_LIMIT from 5 to 30" -ForegroundColor Green
    Write-Host ""
    Write-Host "This should fix the hang issue caused by aggressive rate limiting." -ForegroundColor Green
    Write-Host "The agent will now process requests much faster." -ForegroundColor Green
} else {
    Write-Host "ERROR: .env file not found at $envFile" -ForegroundColor Red
    Write-Host "Please create .env file first using: python scripts/create_env_file.py" -ForegroundColor Yellow
}

