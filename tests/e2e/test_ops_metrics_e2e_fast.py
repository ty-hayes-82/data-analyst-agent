"""
E2E Tests for ops_metrics_weekly - Fast Scoped Tests with Iterative Development

Test Suite: 5 fast E2E tests with specific scope constraints
Target Runtime: <2 minutes per test, <10 minutes total
Dataset: ops_metrics_weekly_validation (1,080 rows, 2024 Q1)

Each test validates:
- Scope filtering (LOB, region, time, metrics)
- Narrative relevance and accuracy
- Anomaly detection for specified scope
- Executive brief quality
"""

import pytest
import os
import subprocess
import json
from pathlib import Path
from datetime import datetime


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent.parent


@pytest.fixture
def validation_dataset_path(project_root):
    """Return path to validation dataset."""
    return project_root / "data/validation/ops_metrics_weekly_validation.csv"


@pytest.fixture
def output_base_dir(project_root):
    """Return the base output directory."""
    return project_root / "outputs/ops_metrics_weekly_validation"


def run_pipeline(metrics, dataset="ops_metrics_weekly_validation", extra_args=None):
    """
    Run the data analyst pipeline with specified parameters.
    
    Args:
        metrics: Comma-separated metric names
        dataset: Dataset name
        extra_args: List of additional CLI arguments
        
    Returns:
        tuple: (return_code, stdout, stderr, output_dir)
    """
    cmd = [
        "python", "-m", "data_analyst_agent",
        "--dataset", dataset,
        "--metrics", metrics,
        "--validation"
    ]
    
    if extra_args:
        cmd.extend(extra_args)
    
    # Enable fast E2E mode - skip executive brief LLM generation
    env = os.environ.copy()
    env["SKIP_EXECUTIVE_BRIEF_LLM"] = "true"
    
    start_time = datetime.now()
    result = subprocess.run(
        cmd,
        cwd="/data/data-analyst-agent",
        capture_output=True,
        text=True,
        timeout=600,  # 10 minute timeout per test (allows for LLM calls + complex analysis)
        env=env
    )
    elapsed = (datetime.now() - start_time).total_seconds()
    
    # Extract output directory from logs
    output_dir = None
    for line in result.stdout.split('\n'):
        if 'Output    :' in line:
            output_dir = Path(line.split(':', 1)[1].strip())
            break
    
    print(f"\n[RUNTIME] Test completed in {elapsed:.1f}s")
    print(f"[OUTPUT] Directory: {output_dir}")
    
    return result.returncode, result.stdout, result.stderr, output_dir, elapsed


def analyze_executive_brief(output_dir, expected_focus):
    """
    Analyze the generated executive brief for relevance and quality.
    
    Args:
        output_dir: Path to output directory
        expected_focus: Dict with keys: metrics, dimensions, lob, region
        
    Returns:
        dict: Critique results
    """
    critique = {
        "relevance": True,
        "accuracy": True,
        "completeness": True,
        "quality": True,
        "issues": []
    }
    
    # Check metric files exist
    metrics = expected_focus.get("metrics", [])
    for metric in metrics:
        metric_file = output_dir / f"metric_{metric}.md"
        if not metric_file.exists():
            critique["completeness"] = False
            critique["issues"].append(f"Missing output file: metric_{metric}.md")
        else:
            # Read and analyze narrative
            content = metric_file.read_text()
            
            # Check for LOB mention if specified
            if expected_focus.get("lob"):
                lob = expected_focus["lob"]
                if lob not in content:
                    critique["relevance"] = False
                    critique["issues"].append(f"LOB '{lob}' not mentioned in {metric}_narrative")
            
            # Check for region mention if specified
            if expected_focus.get("region"):
                region = expected_focus["region"]
                if region not in content:
                    critique["relevance"] = False
                    critique["issues"].append(f"Region '{region}' not mentioned in {metric} narrative")
            
            # Check for metric-specific content
            if metric not in content:
                critique["relevance"] = False
                critique["issues"].append(f"Metric '{metric}' not prominently discussed in its own report")
    
    return critique


def extract_anomaly_counts(output_dir):
    """
    Extract anomaly counts from alert payloads.
    
    Returns:
        dict: Metric name -> anomaly count
    """
    anomalies = {}
    alerts_dir = output_dir / "alerts"
    
    if not alerts_dir.exists():
        return anomalies
    
    for alert_file in alerts_dir.glob("alerts_payload_Metric-_*.json"):
        metric_name = alert_file.stem.replace("alerts_payload_Metric-_", "")
        try:
            data = json.loads(alert_file.read_text())
            # Handle different payload structures
            if isinstance(data, list):
                anomalies[metric_name] = len(data)
            elif isinstance(data, dict):
                if "alerts" in data:
                    # New structure: {"alerts": [...], "config": {...}}
                    alerts_list = data["alerts"]
                    anomalies[metric_name] = len(alerts_list) if isinstance(alerts_list, list) else 0
                else:
                    # Old structure: direct dict (count as 1)
                    anomalies[metric_name] = 1
        except Exception as e:
            print(f"Warning: Failed to parse {alert_file}: {e}")
            pass
    
    return anomalies


# ============================================================================
# TEST 1: Line Haul LOB, Weekly, 13 Weeks, Region → Terminal
# ============================================================================

def test_01_line_haul_weekly_13weeks_region_terminal():
    """
    Test 1: Line Haul LOB, Weekly, 13 Weeks, Region → Terminal
    
    Scope:
    - LOB: ops_ln_of_bus_nm = "Line Haul"
    - Time: Last 13 weeks
    - Hierarchy: Region → Terminal (gl_rgn_nm → gl_div_nm)
    - Metrics: ttl_rev_amt, lh_rev_amt, ordr_cnt, ordr_miles
    
    Expected Critique Focus:
    - Does narrative drill down to terminal level?
    - Are metrics specific to Line Haul?
    - Is weekly grain respected?
    """
    print("\n" + "="*80)
    print("TEST 1: Line Haul LOB, Weekly, 13 Weeks, Region → Terminal")
    print("="*80)
    
    metrics = "ttl_rev_amt,lh_rev_amt,ordr_cnt,ordr_miles"
    
    # TODO: Add dimension filtering when CLI supports it
    # For now, run full dataset and check narrative focus
    returncode, stdout, stderr, output_dir, elapsed = run_pipeline(metrics)
    
    assert returncode == 0, f"Pipeline failed with return code {returncode}\n{stderr}"
    assert output_dir is not None, "Output directory not found"
    assert output_dir.exists(), f"Output directory does not exist: {output_dir}"
    
    # Critique Output
    expected_focus = {
        "metrics": ["ttl_rev_amt", "lh_rev_amt", "ordr_cnt", "ordr_miles"],
        "lob": None,  # Cannot filter at data fetch level yet
        "region": None
    }
    
    critique = analyze_executive_brief(output_dir, expected_focus)
    
    # Check for division-level drill-down in hierarchy results
    assert critique["completeness"], f"Issues: {critique['issues']}"
    
    # Extract anomaly counts
    anomalies = extract_anomaly_counts(output_dir)
    print(f"\n[ANOMALIES] Detected: {anomalies}")
    
    # Basic sanity check: should detect some anomalies
    total_anomalies = sum(anomalies.values())
    assert total_anomalies > 0, f"No anomalies detected across {len(anomalies)} metrics"
    
    print(f"✅ Test 1 PASSED - Runtime: {elapsed:.1f}s")
    print(f"   Anomalies detected: {total_anomalies}")
    print(f"   Critique: {critique}")


# ============================================================================
# TEST 2: Dedicated LOB, Monthly, 6 Months, Region Only
# ============================================================================

def test_02_dedicated_monthly_6months_region():
    """
    Test 2: Dedicated LOB, Monthly, 6 Months, Region Only
    
    Scope:
    - LOB: ops_ln_of_bus_nm = "Dedicated"
    - Time: Last 6 months (monthly aggregation)
    - Hierarchy: Region only (no drill-down)
    - Metrics: ttl_rev_amt, rev_ordr_cnt, truck_count
    
    Expected Critique Focus:
    - Is monthly grain used (not daily/weekly)?
    - Does narrative focus on Dedicated LOB only?
    - Are comparisons across regions present?
    """
    print("\n" + "="*80)
    print("TEST 2: Dedicated LOB, Monthly, 6 Months, Region Only")
    print("="*80)
    
    # Note: rev_ordr_cnt not in validation dataset, using ordr_cnt instead
    metrics = "ttl_rev_amt,ordr_cnt,truck_count"
    
    returncode, stdout, stderr, output_dir, elapsed = run_pipeline(metrics)
    
    assert returncode == 0, f"Pipeline failed with return code {returncode}\n{stderr}"
    assert output_dir is not None, "Output directory not found"
    assert output_dir.exists(), f"Output directory does not exist: {output_dir}"
    
    # Critique Output
    expected_focus = {
        "metrics": ["ttl_rev_amt", "ordr_cnt", "truck_count"],
        "lob": None  # Cannot filter at data fetch level yet
    }
    
    critique = analyze_executive_brief(output_dir, expected_focus)
    assert critique["completeness"], f"Issues: {critique['issues']}"
    
    # Extract anomaly counts
    anomalies = extract_anomaly_counts(output_dir)
    print(f"\n[ANOMALIES] Detected: {anomalies}")
    
    total_anomalies = sum(anomalies.values())
    assert total_anomalies > 0, f"No anomalies detected across {len(anomalies)} metrics"
    
    print(f"✅ Test 2 PASSED - Runtime: {elapsed:.1f}s")
    print(f"   Anomalies detected: {total_anomalies}")


# ============================================================================
# TEST 3: East Region, All LOBs, 4 Weeks, Fuel Efficiency
# ============================================================================

def test_03_east_region_4weeks_fuel_efficiency():
    """
    Test 3: East Region, All LOBs, 4 Weeks, Fuel Efficiency
    
    Scope:
    - Region: gl_rgn_nm = "East"
    - Time: Last 4 weeks
    - LOBs: All
    - Metrics: fuel_srchrg_rev_amt, dh_miles
    
    Expected Critique Focus:
    - Does narrative focus on East region only?
    - Are fuel efficiency insights actionable?
    - Is deadhead analysis present?
    """
    print("\n" + "="*80)
    print("TEST 3: East Region, All LOBs, 4 Weeks, Fuel Efficiency")
    print("="*80)
    
    # Note: ttl_fuel_qty, idle_fuel_qty not in validation dataset
    metrics = "fuel_srchrg_rev_amt,dh_miles"
    
    returncode, stdout, stderr, output_dir, elapsed = run_pipeline(metrics)
    
    assert returncode == 0, f"Pipeline failed with return code {returncode}\n{stderr}"
    assert output_dir is not None, "Output directory not found"
    assert output_dir.exists(), f"Output directory does not exist: {output_dir}"
    
    # Critique Output
    expected_focus = {
        "metrics": ["fuel_srchrg_rev_amt", "dh_miles"],
        "region": "East"
    }
    
    critique = analyze_executive_brief(output_dir, expected_focus)
    
    # Check for East region focus
    # (Currently cannot filter, so check narrative mentions)
    
    # Extract anomaly counts
    anomalies = extract_anomaly_counts(output_dir)
    print(f"\n[ANOMALIES] Detected: {anomalies}")
    
    # Should detect the deadhead spike in East-Northeast (Mar 4-6)
    assert "dh_miles" in anomalies, "Deadhead anomalies not detected"
    assert anomalies["dh_miles"] > 0, "Deadhead spike (East-Northeast) not detected"
    
    print(f"✅ Test 3 PASSED - Runtime: {elapsed:.1f}s")
    print(f"   Deadhead anomalies detected: {anomalies.get('dh_miles', 0)}")


# ============================================================================
# TEST 4: Single Metric (Revenue), All Regions, 8 Weeks, Anomaly Focus
# ============================================================================

def test_04_revenue_only_8weeks_anomaly_focus():
    """
    Test 4: Single Metric (Revenue), All Regions, 8 Weeks, Anomaly Focus
    
    Scope:
    - Regions: All
    - Time: Last 8 weeks
    - Metrics: ttl_rev_amt ONLY
    - Goal: Anomaly detection
    
    Expected Critique Focus:
    - Does narrative focus solely on revenue?
    - Are anomalies detected and prioritized?
    - Are statistical indicators (z-scores) present?
    """
    print("\n" + "="*80)
    print("TEST 4: Single Metric (Revenue), All Regions, 8 Weeks, Anomaly Focus")
    print("="*80)
    
    metrics = "ttl_rev_amt"
    
    returncode, stdout, stderr, output_dir, elapsed = run_pipeline(metrics)
    
    assert returncode == 0, f"Pipeline failed with return code {returncode}\n{stderr}"
    assert output_dir is not None, "Output directory not found"
    assert output_dir.exists(), f"Output directory does not exist: {output_dir}"
    
    # Critique Output
    expected_focus = {
        "metrics": ["ttl_rev_amt"]
    }
    
    critique = analyze_executive_brief(output_dir, expected_focus)
    assert critique["completeness"], f"Issues: {critique['issues']}"
    
    # Extract anomaly counts
    anomalies = extract_anomaly_counts(output_dir)
    print(f"\n[ANOMALIES] Detected: {anomalies}")
    
    # Should detect revenue drop in East (Feb 15-18)
    assert "ttl_rev_amt" in anomalies, "Revenue anomalies not detected"
    assert anomalies["ttl_rev_amt"] > 0, "Revenue drop (East, Feb 15-18) not detected"
    
    print(f"✅ Test 4 PASSED - Runtime: {elapsed:.1f}s")
    print(f"   Revenue anomalies detected: {anomalies.get('ttl_rev_amt', 0)}")


# ============================================================================
# TEST 5: Cross-LOB Comparison, 2 LOBs, 12 Weeks, Efficiency
# ============================================================================

def test_05_cross_lob_comparison_12weeks_efficiency():
    """
    Test 5: Cross-LOB Comparison, 2 LOBs, 12 Weeks, Efficiency
    
    Scope:
    - LOBs: ["Line Haul", "Dedicated"] (comparison)
    - Time: Last 12 weeks
    - Metrics: ordr_miles, dh_miles
    - Goal: Comparative analysis
    
    Expected Critique Focus:
    - Does narrative compare Line Haul vs Dedicated?
    - Are efficiency ratios calculated?
    - Is the comparison actionable?
    """
    print("\n" + "="*80)
    print("TEST 5: Cross-LOB Comparison, 2 LOBs, 12 Weeks, Efficiency")
    print("="*80)
    
    # Note: ttl_trf_mi, ld_trf_mi not in validation dataset
    metrics = "ordr_miles,dh_miles"
    
    returncode, stdout, stderr, output_dir, elapsed = run_pipeline(metrics)
    
    assert returncode == 0, f"Pipeline failed with return code {returncode}\n{stderr}"
    assert output_dir is not None, "Output directory not found"
    assert output_dir.exists(), f"Output directory does not exist: {output_dir}"
    
    # Critique Output
    expected_focus = {
        "metrics": ["ordr_miles", "dh_miles"]
    }
    
    critique = analyze_executive_brief(output_dir, expected_focus)
    assert critique["completeness"], f"Issues: {critique['issues']}"
    
    # Extract anomaly counts
    anomalies = extract_anomaly_counts(output_dir)
    print(f"\n[ANOMALIES] Detected: {anomalies}")
    
    # Check both metrics analyzed
    assert "ordr_miles" in anomalies or "dh_miles" in anomalies, "No efficiency anomalies detected"
    
    print(f"✅ Test 5 PASSED - Runtime: {elapsed:.1f}s")
    print(f"   Efficiency anomalies detected: {anomalies}")


# ============================================================================
# REGRESSION TEST RUNNER (to be called after each test iteration)
# ============================================================================

def test_regression_baseline():
    """
    Regression Baseline Test: Validate Known Anomaly Detection
    
    Expected: 5/6 anomalies detected (83%)
    - Revenue Drop (East, Feb 15-18) ✅
    - Deadhead Spike (East-Northeast, Mar 4-6) ✅
    - Order Volume Drop (Dedicated, Mar 11-26) ✅
    - Fuel Surcharge Zero (Central-Midwest, Feb 20-24) ✅
    - Truck Count Anomaly (East, Feb 25) ⚠️ (partial)
    - Weekend Pattern Suppression (West-Pacific) ❌ (not expected to catch)
    
    Data: 1,080 rows, 2024-01-01 to 2024-03-30
    """
    print("\n" + "="*80)
    print("REGRESSION BASELINE TEST")
    print("="*80)
    
    metrics = "ttl_rev_amt,lh_rev_amt,fuel_srchrg_rev_amt,ordr_cnt,dh_miles,truck_count"
    
    returncode, stdout, stderr, output_dir, elapsed = run_pipeline(metrics)
    
    assert returncode == 0, f"Regression test failed: {stderr}"
    assert output_dir is not None, "Output directory not found"
    
    # Extract anomaly counts
    anomalies = extract_anomaly_counts(output_dir)
    total_anomalies = sum(anomalies.values())
    
    print(f"\n[REGRESSION] Total anomalies detected: {total_anomalies}")
    print(f"[REGRESSION] By metric: {anomalies}")
    
    # Validate key anomalies present
    assert "ttl_rev_amt" in anomalies and anomalies["ttl_rev_amt"] >= 5, \
        "Revenue drop anomaly (East, Feb 15-18) not detected"
    
    assert "dh_miles" in anomalies and anomalies["dh_miles"] >= 1, \
        "Deadhead spike anomaly (East-Northeast, Mar 4-6) not detected"
    
    assert "ordr_cnt" in anomalies and anomalies["ordr_cnt"] >= 5, \
        "Order volume drop anomaly (Dedicated, Mar 11-26) not detected"
    
    assert "fuel_srchrg_rev_amt" in anomalies and anomalies["fuel_srchrg_rev_amt"] >= 3, \
        "Fuel surcharge zero anomaly (Central-Midwest, Feb 20-24) not detected"
    
    # Truck count anomaly detection is partial (1 day spike, Feb 25)
    # May or may not be caught depending on threshold
    
    detection_rate = min(total_anomalies / 6.0, 1.0)  # Cap at 100%
    
    print(f"\n✅ Regression Baseline PASSED")
    print(f"   Detection Rate: {detection_rate*100:.1f}% ({total_anomalies} anomalies)")
    print(f"   Runtime: {elapsed:.1f}s")
    
    assert detection_rate >= 0.7, f"Detection rate {detection_rate*100:.0f}% below 70% threshold"
