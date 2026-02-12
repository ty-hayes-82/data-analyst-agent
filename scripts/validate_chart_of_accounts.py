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
Validate Chart of Accounts

Validates chart_of_accounts for completeness and consistency.
Run on startup or via CLI to ensure data quality.

Usage:
    python scripts/validate_chart_of_accounts.py
    python scripts/validate_chart_of_accounts.py --fix-suggestions
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.chart_loader import validate_chart_completeness


def print_validation_report(report: dict, show_suggestions: bool = False):
    """Print formatted validation report."""
    print("\n" + "="*80)
    print("CHART OF ACCOUNTS VALIDATION REPORT")
    print("="*80)
    
    # Summary statistics
    stats = report.get("stats", {})
    print("\nSUMMARY:")
    print(f"  Total Accounts: {stats.get('total_accounts', 0)}")
    print(f"  Accounts with Category: {stats.get('accounts_with_category', 0)}")
    print(f"  Accounts Missing Category: {stats.get('accounts_missing_category', 0)}")
    print(f"  Accounts with Complete Levels: {stats.get('accounts_with_complete_levels', 0)}")
    print(f"  Accounts with Missing Levels: {stats.get('accounts_with_missing_levels', 0)}")
    
    # Errors
    errors = report.get("errors", [])
    if errors:
        print("\nERRORS (CRITICAL):")
        for error in errors:
            print(f"  ❌ {error}")
    else:
        print("\n✅ No critical errors found!")
    
    # Warnings
    warnings = report.get("warnings", [])
    if warnings:
        print("\nWARNINGS (NON-CRITICAL):")
        for warning in warnings:
            print(f"  ⚠️  {warning}")
    else:
        print("\n✅ No warnings found!")
    
    # Validation status
    print("\n" + "-"*80)
    if report.get("valid"):
        print("✅ VALIDATION: PASSED")
        print("   Chart of accounts is ready for use.")
    else:
        print("❌ VALIDATION: FAILED")
        print("   Critical errors must be fixed before deployment.")
    
    # Detailed issues (if requested)
    if show_suggestions and not report.get("valid"):
        details = report.get("details", {})
        
        print("\n" + "-"*80)
        print("DETAILED ISSUES:")
        
        missing_level_2 = details.get("missing_level_2", [])
        if missing_level_2:
            print(f"\nMissing level_2 ({len(missing_level_2)} accounts):")
            for acc in missing_level_2[:10]:
                print(f"  - {acc}")
            if len(missing_level_2) > 10:
                print(f"  ... and {len(missing_level_2) - 10} more")
        
        missing_category = details.get("missing_category", [])
        if missing_category:
            print(f"\nMissing canonical_category ({len(missing_category)} accounts):")
            for acc in missing_category[:10]:
                print(f"  - {acc}")
            if len(missing_category) > 10:
                print(f"  ... and {len(missing_category) - 10} more")
        
        print("\nFIX SUGGESTIONS:")
        print("  1. Review chart_of_accounts.yaml or chart_of_accounts.json")
        print("  2. Add missing level_2 mappings for ALL accounts")
        print("  3. Assign canonical_category to ALL accounts")
        print("  4. Common categories: Revenue, Wages, Benefits, Fuel, Equipment, etc.")
        print("  5. Re-run this script to verify fixes")
    
    print("="*80 + "\n")


def main():
    """Main validation entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Validate chart of accounts for completeness and consistency"
    )
    parser.add_argument(
        "--fix-suggestions",
        action="store_true",
        help="Show detailed fix suggestions"
    )
    parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        help="Exit with code 1 even on warnings"
    )
    
    args = parser.parse_args()
    
    # Run validation
    try:
        report = validate_chart_completeness()
        
        # Print report
        print_validation_report(report, show_suggestions=args.fix_suggestions)
        
        # Determine exit code
        if not report.get("valid"):
            sys.exit(1)  # Critical errors
        elif args.fail_on_warnings and report.get("warnings"):
            sys.exit(1)  # Warnings present and strict mode
        else:
            sys.exit(0)  # Success
    
    except Exception as e:
        print(f"\n❌ ERROR: Validation failed with exception: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()

