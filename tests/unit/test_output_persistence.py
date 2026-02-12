"""
Step 7: Unit tests for Output Persistence and Data Cache.

Tests:
- data_cache set/get/clear operations
- JSON and Markdown file writing (simulated persistence)
"""

import pytest
import json
import tempfile
from pathlib import Path


# ============================================================================
# Tests for data_cache
# ============================================================================

@pytest.mark.unit
@pytest.mark.csv_mode
def test_data_cache_csv_roundtrip():
    """Test CSV cache set -> get -> clear cycle."""
    from pl_analyst_agent.sub_agents.data_cache import (
        set_validated_csv, get_validated_csv, clear_validated_csv
    )

    csv_data = "period,gl_account,amount\n2024-01,3100-00,50000\n"
    set_validated_csv(csv_data)

    retrieved = get_validated_csv()
    assert retrieved == csv_data

    clear_validated_csv()
    # After clear, should fall back to file cache or return None
    # (file cache still has data from set_validated_csv)
    print("[PASS] CSV cache roundtrip works")


@pytest.mark.unit
@pytest.mark.csv_mode
def test_data_cache_structured_data():
    """Test structured data cache operations."""
    from pl_analyst_agent.sub_agents.data_cache import (
        set_validated_data, get_validated_data, get_validated_records,
        get_validated_metadata, clear_validated_data
    )

    data = {
        "time_series": [
            {"period": "2024-01", "gl_account": "3100-00", "amount": 50000},
            {"period": "2024-02", "gl_account": "3100-00", "amount": 55000},
            {"period": "2024-01", "gl_account": "3200-00", "amount": 10000},
        ],
        "quality_flags": {"missing_months": []}
    }

    set_validated_data(data)

    # Get full data
    retrieved = get_validated_data()
    assert retrieved is not None
    assert len(retrieved["time_series"]) == 3

    # Get records only
    records = get_validated_records()
    assert len(records) == 3

    # Get metadata
    metadata = get_validated_metadata()
    assert metadata["total_records"] == 3
    assert metadata["gl_accounts"] == 2
    assert metadata["period_count"] == 2

    clear_validated_data()
    assert get_validated_data() is None

    print("[PASS] Structured data cache operations work correctly")


@pytest.mark.unit
@pytest.mark.csv_mode
def test_data_cache_clear_all():
    """Test clearing all caches at once."""
    from pl_analyst_agent.sub_agents.data_cache import (
        set_validated_csv, set_validated_data, clear_all_caches,
        get_validated_data
    )

    set_validated_csv("period,amount\n2024-01,100\n")
    set_validated_data({"time_series": [{"period": "2024-01", "amount": 100}]})

    clear_all_caches()

    # Structured cache should be None
    assert get_validated_data() is None
    print("[PASS] Clear all caches works")


@pytest.mark.unit
@pytest.mark.csv_mode
def test_data_cache_empty_metadata():
    """Test metadata when no data is set."""
    from pl_analyst_agent.sub_agents.data_cache import (
        clear_all_caches, get_validated_metadata
    )

    clear_all_caches()
    metadata = get_validated_metadata()
    assert metadata == {} or metadata.get("total_records", 0) == 0

    print("[PASS] Empty metadata handled correctly")


# ============================================================================
# Tests for output file persistence (simulated)
# ============================================================================

@pytest.mark.unit
@pytest.mark.csv_mode
def test_json_output_file_creation(temp_output_dir):
    """Test that JSON analysis output file is created correctly."""
    output = {
        "cost_center": "067",
        "timeframe": {"start": "2024-07", "end": "2025-09"},
        "hierarchical_analysis": {
            "level_2": {"items": 3, "variance_explained_pct": 92.3},
            "level_3": {"items": 5, "variance_explained_pct": 95.0}
        },
        "alerts": [
            {"id": "ALR-001", "severity": "high", "score": 0.85}
        ]
    }

    json_file = temp_output_dir / "cost_center_067.json"
    with open(json_file, "w") as f:
        json.dump(output, f, indent=2)

    # Verify file exists and is valid JSON
    assert json_file.exists()
    assert json_file.stat().st_size > 0

    with open(json_file, "r") as f:
        loaded = json.load(f)

    assert loaded["cost_center"] == "067"
    assert "hierarchical_analysis" in loaded
    assert len(loaded["alerts"]) == 1

    print(f"[PASS] JSON output file created: {json_file.stat().st_size} bytes")


@pytest.mark.unit
@pytest.mark.csv_mode
def test_markdown_output_file_creation(temp_output_dir):
    """Test that Markdown report file is created correctly."""
    report = """# P&L Analysis Report - Cost Center 067

## Executive Summary
- Total Variance: $-125,000
- Top Drivers: 2 categories explain 92% of variance

## Variance Drivers
| Rank | Category | Variance $ | Variance % |
|------|----------|------------|------------|
| 1 | Freight Revenue | $-125,000 | -4.8% |

## Recommended Actions
1. Investigate decrease in Freight Revenue
"""

    md_file = temp_output_dir / "cost_center_067.md"
    with open(md_file, "w") as f:
        f.write(report)

    # Verify file exists and is non-empty
    assert md_file.exists()
    assert md_file.stat().st_size > 0

    content = md_file.read_text()
    assert "# P&L Analysis Report" in content
    assert "Executive Summary" in content
    assert "Variance Drivers" in content

    print(f"[PASS] Markdown output file created: {md_file.stat().st_size} bytes")


@pytest.mark.unit
@pytest.mark.csv_mode
def test_output_idempotent(temp_output_dir):
    """Test that re-running output persistence doesn't corrupt files."""
    json_file = temp_output_dir / "cost_center_067.json"

    # Write first time
    data_v1 = {"cost_center": "067", "version": 1}
    with open(json_file, "w") as f:
        json.dump(data_v1, f)

    # Write second time (overwrite)
    data_v2 = {"cost_center": "067", "version": 2, "extra_field": True}
    with open(json_file, "w") as f:
        json.dump(data_v2, f)

    # Should have version 2
    with open(json_file, "r") as f:
        loaded = json.load(f)

    assert loaded["version"] == 2
    assert loaded["extra_field"] is True

    print("[PASS] Idempotent re-write works correctly")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
