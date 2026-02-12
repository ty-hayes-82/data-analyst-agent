#!/usr/bin/env python3
"""
Quick start script for phase logging in P&L Analyst Agent.

This script demonstrates how to initialize and use the phase logger
for tracking each phase of your analysis pipeline.

Usage:
    python scripts/setup_phase_logging.py
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pl_analyst_agent.utils.phase_logger import PhaseLogger, phase_logged


def demonstrate_basic_usage():
    """Demonstrate basic phase logging usage."""
    print("\n" + "="*80)
    print("DEMONSTRATION: Basic Phase Logging")
    print("="*80 + "\n")
    
    # Initialize phase logger for cost center 067
    phase_logger = PhaseLogger(cost_center="067")
    
    # Phase 1: Data Ingestion
    phase_logger.start_phase(
        "Phase 1: Data Ingestion & Validation",
        description="Fetches P&L data, ops metrics, and validates data quality",
        input_data={
            "cost_center": "067",
            "date_range": "2023-01 to 2024-12"
        }
    )
    
    # Simulate work
    import time
    time.sleep(1)
    
    # Log metrics
    phase_logger.log_metric("records_fetched", 285)
    phase_logger.log_metric("data_quality_score", 0.95)
    phase_logger.log_metric("missing_periods", 2)
    
    # End phase
    phase_logger.end_phase(
        "Phase 1: Data Ingestion & Validation",
        output_data={
            "status": "completed",
            "record_count": 285,
            "quality_flags": {"missing_periods": 2}
        },
        status="completed"
    )
    
    # Phase 2: Category Analysis
    phase_logger.start_phase(
        "Phase 2: Category Aggregation & Prioritization",
        description="Aggregates GLs into categories and identifies top variance drivers"
    )
    
    time.sleep(0.5)
    
    phase_logger.log_metric("categories_identified", 8)
    phase_logger.log_metric("material_categories", 5)
    phase_logger.log_metric("total_variance_dollars", 425000)
    
    phase_logger.end_phase(
        "Phase 2: Category Aggregation & Prioritization",
        output_data={
            "top_categories": ["Fuel", "Labor", "Maintenance"],
            "coverage_pct": 85.2
        },
        status="completed"
    )
    
    # Phase 3: GL Drill-Down
    phase_logger.start_phase(
        "Phase 3: GL Drill-Down",
        description="Analyzes individual GLs within top categories for root causes"
    )
    
    time.sleep(0.3)
    
    phase_logger.log_metric("gls_analyzed", 12)
    phase_logger.log_metric("root_causes_classified", 12)
    phase_logger.log_warning("GL 6020 has unusual variance pattern")
    
    phase_logger.end_phase(
        "Phase 3: GL Drill-Down",
        output_data={
            "gl_count": 12,
            "root_cause_distribution": {
                "operational": 8,
                "timing": 2,
                "accrual": 2
            }
        },
        status="completed"
    )
    
    # Phase 4: Parallel Analysis
    phase_logger.start_phase(
        "Phase 4: Parallel Analysis",
        description="Runs 6 analysis agents concurrently"
    )
    
    time.sleep(1.5)
    
    phase_logger.log_metric("agents_executed", 6)
    phase_logger.log_metric("total_analysis_time", 45.2)
    phase_logger.log_metric("failed_agents", 0)
    
    phase_logger.end_phase(
        "Phase 4: Parallel Analysis",
        output_data={
            "completed_agents": 6,
            "failed_agents": []
        },
        status="completed"
    )
    
    # Phase 5: Synthesis
    phase_logger.start_phase(
        "Phase 5: Synthesis & Structuring",
        description="Generates 3-level output (Executive Summary, Category Analysis, GL Drill-Down)"
    )
    
    time.sleep(0.5)
    
    phase_logger.log_metric("executive_bullets_count", 5)
    phase_logger.log_metric("categories_in_summary", 3)
    phase_logger.log_metric("gls_in_drilldown", 12)
    
    phase_logger.end_phase(
        "Phase 5: Synthesis & Structuring",
        output_data={
            "levels_generated": 3,
            "executive_summary_complete": True
        },
        status="completed"
    )
    
    # Phase 6: Alert Scoring & Persistence
    phase_logger.start_phase(
        "Phase 6: Alert Scoring & Persistence",
        description="Scores alerts by priority and saves results to JSON files"
    )
    
    time.sleep(0.3)
    
    phase_logger.log_metric("alerts_extracted", 8)
    phase_logger.log_metric("high_priority_alerts", 2)
    phase_logger.log_metric("output_files_written", 2)
    
    phase_logger.end_phase(
        "Phase 6: Alert Scoring & Persistence",
        output_data={
            "alerts_scored": 8,
            "files_saved": ["cost_center_067.json", "alerts_payload_cc067.json"]
        },
        status="completed"
    )
    
    # Save complete summary
    summary_file = phase_logger.save_phase_summary()
    
    print("\n" + "="*80)
    print(f"Phase logging complete!")
    print(f"Summary saved to: {summary_file}")
    print(f"Log file: {phase_logger.log_file}")
    print("="*80 + "\n")
    
    return phase_logger


def demonstrate_error_handling():
    """Demonstrate error handling in phase logging."""
    print("\n" + "="*80)
    print("DEMONSTRATION: Error Handling")
    print("="*80 + "\n")
    
    phase_logger = PhaseLogger(cost_center="999")
    
    phase_logger.start_phase(
        "Phase 1: Data Ingestion & Validation",
        description="Attempting to fetch data"
    )
    
    try:
        # Simulate an error
        raise ValueError("Cost center 999 not found in database")
    except Exception as e:
        phase_logger.log_error("Data fetch failed", e)
        phase_logger.end_phase("Phase 1: Data Ingestion & Validation", status="failed")
    
    summary_file = phase_logger.save_phase_summary()
    
    print(f"\nError logged successfully. Summary saved to: {summary_file}\n")


def view_phase_summary(summary_file: Path):
    """Display phase summary in readable format."""
    import json
    
    print("\n" + "="*80)
    print("PHASE EXECUTION SUMMARY")
    print("="*80 + "\n")
    
    with open(summary_file, 'r', encoding='utf-8') as f:
        summary = json.load(f)
    
    print(f"Cost Center: {summary['cost_center']}")
    print(f"Session Duration: {summary['total_duration_seconds']:.2f}s")
    print(f"\nPhases Executed: {summary['summary_statistics']['total_phases']}")
    print(f"Success Rate: {summary['summary_statistics']['success_rate'] * 100:.1f}%")
    print(f"Total Errors: {summary['summary_statistics']['total_errors']}")
    print(f"Total Warnings: {summary['summary_statistics']['total_warnings']}")
    
    print("\n" + "-"*80)
    print("PHASE BREAKDOWN")
    print("-"*80)
    
    for phase_key, phase_info in summary['phases'].items():
        status_symbol = {
            "completed": "✓",
            "failed": "✗",
            "skipped": "○",
            "in_progress": "..."
        }.get(phase_info['status'], "?")
        
        print(f"\n{status_symbol} {phase_info['name']}")
        print(f"   Duration: {phase_info.get('duration_seconds', 0):.2f}s")
        print(f"   Status: {phase_info['status'].upper()}")
        
        if phase_info.get('metrics'):
            print(f"   Metrics:")
            for metric_name, metric_value in phase_info['metrics'].items():
                print(f"     - {metric_name}: {metric_value}")
        
        if phase_info.get('errors'):
            print(f"   Errors: {len(phase_info['errors'])}")
            for error in phase_info['errors']:
                print(f"     - {error['message']}")
        
        if phase_info.get('warnings'):
            print(f"   Warnings: {len(phase_info['warnings'])}")
            for warning in phase_info['warnings']:
                print(f"     - {warning['message']}")
    
    print("\n" + "="*80 + "\n")


def setup_environment():
    """Set up environment for phase logging."""
    print("\n" + "="*80)
    print("SETUP: Phase Logging Environment")
    print("="*80 + "\n")
    
    # Create logs directory
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)
    print(f"✓ Logs directory created: {logs_dir}")
    
    # Create docs directory if needed
    docs_dir = project_root / "docs"
    docs_dir.mkdir(exist_ok=True)
    print(f"✓ Docs directory exists: {docs_dir}")
    
    # Check for config file
    config_file = project_root / "config" / "phase_logging.yaml"
    if config_file.exists():
        print(f"✓ Configuration file found: {config_file}")
    else:
        print(f"⚠ Configuration file not found: {config_file}")
        print(f"  A default configuration has been created.")
    
    # Check for phase logger module
    logger_module = project_root / "pl_analyst_agent" / "utils" / "phase_logger.py"
    if logger_module.exists():
        print(f"✓ Phase logger module found: {logger_module}")
    else:
        print(f"✗ Phase logger module not found: {logger_module}")
        print(f"  Please ensure the module is properly installed.")
    
    print("\n" + "="*80 + "\n")


def main():
    """Main entry point."""
    print("\n" + "="*80)
    print("P&L ANALYST - PHASE LOGGING SETUP")
    print("="*80)
    
    # Setup environment
    setup_environment()
    
    # Demonstrate basic usage
    phase_logger = demonstrate_basic_usage()
    
    # Demonstrate error handling
    demonstrate_error_handling()
    
    # View the summary
    if phase_logger.log_file.exists():
        # Find the most recent summary file
        logs_dir = project_root / "logs"
        summary_files = sorted(logs_dir.glob("phase_summary_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        
        if summary_files:
            view_phase_summary(summary_files[0])
    
    print("\n" + "="*80)
    print("NEXT STEPS:")
    print("="*80)
    print("\n1. Review the generated log files in logs/")
    print("2. Read the integration guide: docs/PHASE_LOGGING_GUIDE.md")
    print("3. Update your agent files to use PhaseLogger")
    print("4. Configure phase_logging.yaml to customize behavior")
    print("5. Test with: python test_with_csv.py")
    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    main()

