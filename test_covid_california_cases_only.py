import subprocess
import os
from pathlib import Path

def test_covid_ca_cases_minimal():
    """
    Minimal E2E: California, cases metric only.
    Target: <60 sec runtime, executive brief generated.
    """
    env = os.environ.copy()
    env['ACTIVE_DATASET'] = 'covid_us_counties'
    env['DATA_ANALYST_METRICS'] = 'cases'
    # Note: Add state filter via dimension_filters or CLI if supported
    
    result = subprocess.run(
        ['python', '-m', 'data_analyst_agent', 
         '--metrics', 'cases',
         '--dimension', 'state', 
         '--dimension-value', 'California'],
        env=env,
        capture_output=True,
        text=True,
        timeout=120  # 2 min max
    )
    
    assert result.returncode == 0, f"Pipeline failed: {result.stderr}"
    
    # Verify output exists
    outputs = Path('outputs/covid_us_counties')
    latest = max(outputs.glob('202*'), key=lambda p: p.name)
    brief = latest / 'executive_brief.md'
    
    assert brief.exists(), "Executive brief not generated"
    assert brief.stat().st_size > 1000, "Brief too small (likely empty)"
    
    # Verify aggregation happened
    assert 'Aggregation' in result.stdout or 'aggregated' in result.stdout.lower()
    
    print(f"✅ Phase 1 passed: {latest.name}")

if __name__ == '__main__':
    test_covid_ca_cases_minimal()
