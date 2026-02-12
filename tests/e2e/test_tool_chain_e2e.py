"""
Step 10: End-to-End Test - Full Tool Chain.

Tests the complete pipeline from user query to final output files using
actual tool functions with real PL-067 data:
1. Data Loading (TestDataLoader)
2. Data Validation (reshape, flip, join)
3. Cache Storage
4. Statistical Insights (compute_statistical_summary)
5. Hierarchy Drill-Down (compute_level_statistics levels 2-5)
6. Alert Extraction and Scoring
7. Report Synthesis (generate_markdown_report)
8. Output Persistence (JSON + Markdown files)
"""

import pytest
import json
import importlib
import time
import pandas as pd
from io import StringIO
from pathlib import Path

from tests.fixtures.test_data_loader import TestDataLoader
from tests.utils.import_helpers import (
    import_data_validation_tool,
    import_hierarchy_ranker_tool,
    import_report_synthesis_tool,
    import_alert_scoring_tool,
)
from pl_analyst_agent.sub_agents.data_cache import (
    set_validated_csv, get_validated_csv, clear_all_caches, _CSV_CACHE_FILE
)


# ============================================================================
# Dynamic import helpers for numeric-prefix directories
# ============================================================================

def _import_stat_tool(tool_name: str):
    mod = importlib.import_module(
        f"pl_analyst_agent.sub_agents.02_statistical_insights_agent.tools.{tool_name}"
    )
    return getattr(mod, tool_name)


def _import_hierarchy_tool(tool_name: str):
    mod = importlib.import_module(
        f"pl_analyst_agent.sub_agents.03_hierarchy_variance_ranker_agent.tools.{tool_name}"
    )
    return getattr(mod, tool_name)


# ============================================================================
# E2E Test: Complete tool chain
# ============================================================================

@pytest.mark.e2e
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_full_tool_chain_e2e(temp_output_dir):
    """
    End-to-end test running every tool in the pipeline sequence.

    Pipeline: Load -> Reshape -> Flip -> Join Metadata -> Cache
              -> Statistical Summary -> Hierarchy Drill-Down (L2-L5)
              -> Alert Extraction -> Alert Scoring
              -> Report Synthesis -> Output Files
    """
    start_time = time.time()
    cost_center = "067"

    # Clean state
    clear_all_caches()
    if _CSV_CACHE_FILE.exists():
        _CSV_CACHE_FILE.unlink()

    # ==================================================================
    # Phase 1: Data Loading
    # ==================================================================
    print("\n--- Phase 1: Data Loading ---")
    loader = TestDataLoader()
    pl_df = loader.load_pl_067_csv()
    ts_df = loader.convert_to_time_series_format(pl_df)
    assert len(ts_df) > 0, "Time series data should not be empty"
    print(f"  Loaded {len(ts_df)} rows, {ts_df['gl_account'].nunique()} GL accounts")

    # ==================================================================
    # Phase 2: Data Validation Pipeline
    # ==================================================================
    print("\n--- Phase 2: Data Validation ---")
    reshape_mod = import_data_validation_tool("reshape_and_validate")
    flip_mod = import_data_validation_tool("flip_revenue_signs")
    join_mod = import_data_validation_tool("join_chart_metadata")

    # 2a: Reshape and validate (expects JSON input, not CSV)
    records = ts_df.to_dict(orient="records")
    json_input = json.dumps({"time_series": records})
    reshape_result = json.loads(await reshape_mod.reshape_and_validate(json_input))
    assert "error" not in reshape_result, f"Reshape error: {reshape_result.get('error')}"
    time_series = reshape_result["time_series"]
    print(f"  Reshape: {len(time_series)} records validated")

    # Convert time_series to CSV for subsequent tools
    validated_csv = pd.DataFrame(time_series).to_csv(index=False)

    # 2b: Flip revenue signs (expects CSV input)
    flipped_csv = await flip_mod.flip_revenue_signs(validated_csv)
    flipped_df = pd.read_csv(StringIO(flipped_csv))
    assert "sign_flipped" in flipped_df.columns
    print(f"  Sign flip: {flipped_df['sign_flipped'].sum()} rows flipped")

    # 2c: Join chart metadata (expects CSV input)
    enriched_csv = await join_mod.join_chart_metadata(flipped_csv)
    enriched_df = pd.read_csv(StringIO(enriched_csv))
    has_level_2 = "level_2" in enriched_df.columns or "level_2_y" in enriched_df.columns
    assert has_level_2, f"Missing level_2 hierarchy column. Columns: {list(enriched_df.columns)}"
    print(f"  Metadata join: {len(enriched_df)} rows with hierarchy")

    # Add account_name for statistical tools
    if "account_name" not in enriched_df.columns:
        enriched_df["account_name"] = enriched_df["gl_account"]
    enriched_csv = enriched_df.to_csv(index=False)

    # ==================================================================
    # Phase 3: Cache Storage
    # ==================================================================
    print("\n--- Phase 3: Cache Storage ---")
    set_validated_csv(enriched_csv)
    cached = get_validated_csv()
    assert cached is not None, "Cache should contain data"
    print(f"  Cached {len(cached)} bytes")

    # ==================================================================
    # Phase 4: Statistical Insights
    # ==================================================================
    print("\n--- Phase 4: Statistical Insights ---")
    compute_statistical_summary = _import_stat_tool("compute_statistical_summary")
    stat_result_str = await compute_statistical_summary()
    stat_result = json.loads(stat_result_str)
    assert "error" not in stat_result, f"Stats error: {stat_result.get('error')}"

    stats = stat_result["summary_stats"]
    print(f"  Accounts: {stats['total_accounts']}, Periods: {stats['total_periods']}")
    print(f"  Anomalies: {len(stat_result.get('anomalies', []))}")
    print(f"  Top drivers: {len(stat_result.get('top_drivers', []))}")
    print(f"  MAD outliers: {stat_result.get('mad_outliers', {}).get('summary', {}).get('total_outliers_detected', 0)}")

    # ==================================================================
    # Phase 5: Hierarchy Drill-Down (levels 2-5)
    # ==================================================================
    print("\n--- Phase 5: Hierarchy Drill-Down ---")
    compute_level_statistics = _import_hierarchy_tool("compute_level_statistics")

    levels_analyzed = []
    level_results = {}

    for level in [2, 3, 4, 5]:
        level_result_str = await compute_level_statistics(level=level)
        level_result = json.loads(level_result_str)

        if "error" in level_result:
            print(f"  Level {level}: ERROR - {level_result.get('error')}")
            continue

        if level_result.get("is_duplicate"):
            print(f"  Level {level}: SKIP (duplicate of Level {level_result.get('duplicate_of')})")
            continue

        levels_analyzed.append(level)
        level_results[f"level_{level}"] = level_result

        items = level_result.get("items_analyzed", 0)
        drivers = len(level_result.get("top_drivers", []))
        print(f"  Level {level}: {items} items, {drivers} top drivers")

    assert len(levels_analyzed) >= 2, "Should analyze at least 2 hierarchy levels"

    # Build hierarchical result
    hierarchical_result = {
        "analysis_type": "hierarchical_drill_down",
        "cost_center": cost_center,
        "levels_analyzed": levels_analyzed,
        "drill_down_path": " -> ".join(f"Level {l}" for l in levels_analyzed),
        "level_results": level_results
    }

    # ==================================================================
    # Phase 6: Alert Extraction and Scoring
    # ==================================================================
    print("\n--- Phase 6: Alert Scoring ---")
    extract_mod = import_alert_scoring_tool("extract_alerts_from_analysis")
    score_mod = import_alert_scoring_tool("score_alerts")

    # Extract alerts from statistical summary
    alerts_result_str = await extract_mod.extract_alerts_from_analysis(
        statistical_summary=json.dumps(stat_result),
        cost_center=cost_center
    )
    alerts_result = json.loads(alerts_result_str)
    alert_count = len(alerts_result.get("alerts", []))
    print(f"  Extracted {alert_count} alerts")

    # Score alerts (only if there are alerts)
    scored_alerts = None
    if alert_count > 0:
        scored_result_str = await score_mod.score_alerts(json.dumps(alerts_result))
        scored_alerts = json.loads(scored_result_str)

        if "error" not in scored_alerts:
            top_count = len(scored_alerts.get("top_alerts", []))
            print(f"  Scored alerts: {scored_alerts.get('total_alerts_received', 0)} received, "
                  f"{top_count} in top list")

            # Show top alert priority
            for alert in scored_alerts.get("top_alerts", [])[:3]:
                print(f"    - {alert.get('id', 'N/A')}: score={alert.get('score', 0):.2f}, "
                      f"priority={alert.get('priority', 'N/A')}")
        else:
            print(f"  Scoring returned: {scored_alerts.get('error')}")
    else:
        print("  No alerts to score")

    # ==================================================================
    # Phase 7: Report Synthesis
    # ==================================================================
    print("\n--- Phase 7: Report Synthesis ---")
    generate_report = import_report_synthesis_tool("generate_markdown_report")

    # generate_markdown_report takes hierarchical_results (JSON str) and cost_center
    hierarchical_input = json.dumps({
        "hierarchical_results": hierarchical_result,
        "statistical_summary": stat_result,
        "alerts": scored_alerts if scored_alerts and "error" not in scored_alerts else {"top_alerts": []}
    })

    report_str = await generate_report.generate_markdown_report(
        hierarchical_results=hierarchical_input,
        cost_center=cost_center
    )

    # Report may return JSON with the markdown inside
    try:
        report_data = json.loads(report_str)
        markdown_report = report_data.get("report", report_str)
    except json.JSONDecodeError:
        markdown_report = report_str

    assert len(markdown_report) > 100, "Report should be substantial"
    assert "067" in markdown_report or "Cost Center" in markdown_report
    print(f"  Report generated: {len(markdown_report)} characters")

    # ==================================================================
    # Phase 8: Output Persistence
    # ==================================================================
    print("\n--- Phase 8: Output Persistence ---")

    # Write JSON output
    json_output = {
        "cost_center": cost_center,
        "hierarchical_analysis": hierarchical_result,
        "statistical_summary": {
            "total_accounts": stats["total_accounts"],
            "total_periods": stats["total_periods"],
            "anomaly_count": len(stat_result.get("anomalies", [])),
            "top_drivers_count": len(stat_result.get("top_drivers", [])),
        },
        "alerts": scored_alerts if scored_alerts and "error" not in scored_alerts else {"top_alerts": []},
        "metadata": {
            "test_mode": True,
            "pipeline_version": "csv_test",
        }
    }

    json_file = temp_output_dir / f"cost_center_{cost_center}.json"
    with open(json_file, "w") as f:
        json.dump(json_output, f, indent=2)

    assert json_file.exists()
    assert json_file.stat().st_size > 0
    print(f"  JSON output: {json_file.stat().st_size} bytes")

    # Write Markdown output
    md_file = temp_output_dir / f"cost_center_{cost_center}.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(markdown_report)

    assert md_file.exists()
    assert md_file.stat().st_size > 0
    print(f"  Markdown output: {md_file.stat().st_size} bytes")

    # Verify JSON is valid by re-reading
    with open(json_file, "r") as f:
        reloaded = json.load(f)
    assert reloaded["cost_center"] == cost_center
    assert "hierarchical_analysis" in reloaded

    # ==================================================================
    # Final Summary
    # ==================================================================
    elapsed = time.time() - start_time
    print(f"\n=== E2E COMPLETE ===")
    print(f"  Cost Center: {cost_center}")
    print(f"  Data: {len(ts_df)} rows, {ts_df['gl_account'].nunique()} GL accounts")
    print(f"  Hierarchy Levels: {levels_analyzed}")
    print(f"  Alerts: {alert_count} extracted")
    print(f"  Report: {len(markdown_report)} chars")
    print(f"  Output files: {json_file.name}, {md_file.name}")
    print(f"  Time: {elapsed:.1f}s")

    assert elapsed < 300, f"Pipeline took {elapsed:.1f}s (expected < 300s)"
    print(f"\n[PASS] Full E2E pipeline completed in {elapsed:.1f}s")

    # Cleanup
    clear_all_caches()


# ============================================================================
# E2E Test: Verify output file contents
# ============================================================================

@pytest.mark.e2e
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_output_files_cross_reference(temp_output_dir):
    """
    Test that output files can be cross-referenced back to source data.
    Runs a minimal pipeline and verifies GL accounts in output match source.
    """
    cost_center = "067"

    # Clean state
    clear_all_caches()
    if _CSV_CACHE_FILE.exists():
        _CSV_CACHE_FILE.unlink()

    # Load and cache data
    loader = TestDataLoader()
    pl_df = loader.load_pl_067_csv()
    ts_df = loader.convert_to_time_series_format(pl_df)
    if "account_name" not in ts_df.columns:
        ts_df["account_name"] = ts_df["gl_account"]

    set_validated_csv(ts_df.to_csv(index=False))

    # Run statistical summary
    compute_stat = _import_stat_tool("compute_statistical_summary")
    stat_str = await compute_stat()
    stat_result = json.loads(stat_str)

    assert "error" not in stat_result

    # Verify GL accounts in top_drivers exist in source data
    source_accounts = set(ts_df["gl_account"].unique())
    for driver in stat_result.get("top_drivers", []):
        acct = driver.get("account", "")
        assert acct in source_accounts, \
            f"Driver account {acct} not found in source data"

    # Verify anomaly accounts exist in source
    for anomaly in stat_result.get("anomalies", []):
        acct = anomaly.get("account", "")
        assert acct in source_accounts, \
            f"Anomaly account {acct} not found in source data"

    print(f"[PASS] Cross-reference verified: all GL accounts in output match source data")
    print(f"  Source accounts: {len(source_accounts)}")
    print(f"  Top drivers verified: {len(stat_result.get('top_drivers', []))}")
    print(f"  Anomalies verified: {len(stat_result.get('anomalies', []))}")

    # Cleanup
    clear_all_caches()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
