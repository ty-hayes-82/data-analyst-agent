# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Interactive CLI to update business context after monthly P&L review.

Usage:
    python scripts/update_business_context.py --cost-center 067 --period 2025-09
    python scripts/update_business_context.py --add-pattern
    python scripts/update_business_context.py --add-suppression
"""

import argparse
from datetime import datetime
from pathlib import Path
import sys
import yaml


CONFIG_PATH = Path(__file__).parent.parent / "config" / "business_context.yaml"


def load_context():
    """Load current business context."""
    if not CONFIG_PATH.exists():
        return {
            "known_patterns": {},
            "gl_root_cause_history": {},
            "suppression_rules": {},
            "root_cause_taxonomy": {}
        }
    
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def save_context(context):
    """Save updated business context."""
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(context, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    print(f"\nSaved updates to {CONFIG_PATH}")


def add_root_cause(context, args):
    """Add root cause for a GL variance."""
    print("\n=== Add Root Cause Entry ===")
    
    gl_account = input("GL Account (e.g., 3110-00): ").strip()
    if not gl_account:
        print("ERROR: GL account required")
        return
    
    period = args.period or input("Period (YYYY-MM): ").strip()
    
    try:
        variance_dollar = float(input("Variance $ (e.g., 100472 or -50000): ").strip())
    except ValueError:
        print("ERROR: Invalid dollar amount")
        return
    
    print("\nRoot Cause Categories:")
    print("  1. operational")
    print("  2. market")
    print("  3. seasonal")
    print("  4. data_quality")
    print("  5. one_time")
    root_cause = input("Select root cause (1-5): ").strip()
    
    root_cause_map = {
        "1": "operational",
        "2": "market",
        "3": "seasonal",
        "4": "data_quality",
        "5": "one_time"
    }
    root_cause = root_cause_map.get(root_cause, "operational")
    
    sub_classification = input("Sub-classification (e.g., rate_change, volume_mix): ").strip()
    
    one_time_input = input("One-time event? (y/n): ").strip().lower()
    one_time = one_time_input == 'y'
    
    reasoning = input("Reasoning (brief explanation): ").strip()
    
    validated_by = input("Validated by (name/role): ").strip() or "Analyst"
    
    follow_up = input("Follow-up action (optional): ").strip() or "Monitor trends"
    
    status = input("Status (active_monitoring/resolved/recurring) [active_monitoring]: ").strip() or "active_monitoring"
    
    # Create entry
    entry = {
        "period": period,
        "variance_dollar": variance_dollar,
        "root_cause": root_cause,
        "sub_classification": sub_classification,
        "one_time": one_time,
        "reasoning": reasoning,
        "validated_by": validated_by,
        "validation_date": datetime.now().strftime("%Y-%m-%d"),
        "follow_up_action": follow_up,
        "status": status
    }
    
    # Add to context
    if "gl_root_cause_history" not in context:
        context["gl_root_cause_history"] = {}
    
    if gl_account not in context["gl_root_cause_history"]:
        context["gl_root_cause_history"][gl_account] = []
    
    context["gl_root_cause_history"][gl_account].append(entry)
    
    print(f"\nAdded root cause entry for GL {gl_account}")
    save_context(context)


def add_pattern(context, args):
    """Add a known pattern."""
    print("\n=== Add Known Pattern ===")
    
    pattern_id = input("Pattern ID (e.g., 067_freight_q4_spike): ").strip()
    if not pattern_id:
        print("ERROR: Pattern ID required")
        return
    
    print("\nPattern Types:")
    print("  1. seasonal")
    print("  2. operational")
    print("  3. market")
    print("  4. one_time")
    pattern_type = input("Select pattern type (1-4): ").strip()
    
    pattern_type_map = {
        "1": "seasonal",
        "2": "operational",
        "3": "market",
        "4": "one_time"
    }
    pattern_type = pattern_type_map.get(pattern_type, "operational")
    
    description = input("Description: ").strip()
    
    affected_gls_input = input("Affected GLs (comma-separated, e.g., 3100-00,3100-01): ").strip()
    affected_gls = [gl.strip() for gl in affected_gls_input.split(",")] if affected_gls_input else []
    
    cost_centers_input = input("Cost Centers (comma-separated, e.g., 067,123): ").strip()
    cost_centers = [cc.strip() for cc in cost_centers_input.split(",")] if cost_centers_input else []
    
    suppress_alerts_input = input("Suppress alerts for this pattern? (y/n): ").strip().lower()
    suppress_alerts = suppress_alerts_input == 'y'
    
    documented_by = input("Documented by (name/role): ").strip() or "Analyst"
    
    # Create entry
    entry = {
        "pattern_type": pattern_type,
        "description": description,
        "affected_gls": affected_gls,
        "cost_centers": cost_centers,
        "suppress_alerts": suppress_alerts,
        "documented_by": documented_by,
        "documented_date": datetime.now().strftime("%Y-%m-%d")
    }
    
    # Add seasonal months if applicable
    if pattern_type == "seasonal":
        months_input = input("Applicable months (comma-separated, e.g., 10,11,12): ").strip()
        if months_input:
            entry["months"] = [int(m.strip()) for m in months_input.split(",")]
    
    # Add to context
    if "known_patterns" not in context:
        context["known_patterns"] = {}
    
    context["known_patterns"][pattern_id] = entry
    
    print(f"\nAdded pattern: {pattern_id}")
    save_context(context)


def add_suppression(context, args):
    """Add a suppression rule."""
    print("\n=== Add Suppression Rule ===")
    
    rule_id = input("Rule ID (e.g., 067_period_14_accruals): ").strip()
    if not rule_id:
        print("ERROR: Rule ID required")
        return
    
    description = input("Description: ").strip()
    
    affected_gls_input = input("Affected GLs (comma-separated, wildcards allowed, e.g., 4100-*,4200-*): ").strip()
    affected_gls = [gl.strip() for gl in affected_gls_input.split(",")] if affected_gls_input else []
    
    cost_centers_input = input("Cost Centers (comma-separated, * for all): ").strip()
    cost_centers = [cc.strip() for cc in cost_centers_input.split(",")] if cost_centers_input else ["*"]
    
    periods_input = input("Periods (comma-separated, blank for all): ").strip()
    periods = [int(p.strip()) for p in periods_input.split(",") if p.strip()] if periods_input else []
    
    try:
        suppress_below = float(input("Suppress severity below (0.0-1.0) [0.5]: ").strip() or "0.5")
    except ValueError:
        suppress_below = 0.5
    
    reason = input("Reason: ").strip()
    
    created_by = input("Created by (name/role): ").strip() or "Analyst"
    
    # Create entry
    entry = {
        "description": description,
        "affected_gls": affected_gls,
        "cost_centers": cost_centers,
        "periods": periods,
        "suppress_severity_below": suppress_below,
        "reason": reason,
        "active": True,
        "created_by": created_by,
        "created_date": datetime.now().strftime("%Y-%m-%d")
    }
    
    # Add to context
    if "suppression_rules" not in context:
        context["suppression_rules"] = {}
    
    context["suppression_rules"][rule_id] = entry
    
    print(f"\nAdded suppression rule: {rule_id}")
    save_context(context)


def list_entries(context, entry_type):
    """List existing entries."""
    print(f"\n=== Current {entry_type.replace('_', ' ').title()} ===")
    
    entries = context.get(entry_type, {})
    if not entries:
        print("  (none)")
        return
    
    for key, value in entries.items():
        print(f"\n{key}:")
        if entry_type == "gl_root_cause_history":
            print(f"  {len(value)} entries")
            for entry in value[:3]:  # Show first 3
                print(f"    - {entry.get('period')}: {entry.get('root_cause')} ({entry.get('variance_dollar', 0):+,.0f})")
        else:
            print(f"  Type: {value.get('pattern_type') or value.get('description', 'N/A')}")
            print(f"  Active: {value.get('active', value.get('suppress_alerts', True))}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Update business context after monthly P&L review"
    )
    parser.add_argument("--cost-center", help="Cost center code")
    parser.add_argument("--period", help="Analysis period (YYYY-MM)")
    parser.add_argument("--add-root-cause", action="store_true", help="Add root cause entry")
    parser.add_argument("--add-pattern", action="store_true", help="Add known pattern")
    parser.add_argument("--add-suppression", action="store_true", help="Add suppression rule")
    parser.add_argument("--list", choices=["patterns", "root_causes", "suppressions"], 
                       help="List existing entries")
    
    args = parser.parse_args()
    
    # Load context
    context = load_context()
    
    # Handle list command
    if args.list:
        entry_type_map = {
            "patterns": "known_patterns",
            "root_causes": "gl_root_cause_history",
            "suppressions": "suppression_rules"
        }
        list_entries(context, entry_type_map[args.list])
        return
    
    # Interactive mode
    if args.add_root_cause:
        add_root_cause(context, args)
    elif args.add_pattern:
        add_pattern(context, args)
    elif args.add_suppression:
        add_suppression(context, args)
    else:
        # Main menu
        print("\n=== Business Context Update Tool ===")
        print("1. Add root cause for GL variance")
        print("2. Add known pattern")
        print("3. Add suppression rule")
        print("4. List patterns")
        print("5. List root causes")
        print("6. List suppressions")
        print("7. Exit")
        
        choice = input("\nSelect option (1-7): ").strip()
        
        if choice == "1":
            add_root_cause(context, args)
        elif choice == "2":
            add_pattern(context, args)
        elif choice == "3":
            add_suppression(context, args)
        elif choice == "4":
            list_entries(context, "known_patterns")
        elif choice == "5":
            list_entries(context, "gl_root_cause_history")
        elif choice == "6":
            list_entries(context, "suppression_rules")
        elif choice == "7":
            print("Exiting...")
        else:
            print("Invalid choice")


if __name__ == "__main__":
    main()

