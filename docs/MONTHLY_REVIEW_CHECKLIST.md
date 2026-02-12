# Monthly P&L Review Checklist

## Pre-Analysis (Start of Month)

- [ ] **Validate Chart of Accounts**
  ```bash
  python scripts/validate_chart_of_accounts.py
  ```
  - Fix any missing level mappings or categories
  - Update chart if new GLs were added

- [ ] **Review Business Context**
  - Open `config/business_context.yaml`
  - Deactivate expired suppression rules
  - Review open action items from prior month
  - Check for patterns that need status updates

- [ ] **Regenerate Materiality Thresholds** (quarterly or as needed)
  ```bash
  python scripts/calculate_materiality_thresholds.py --data-source csv --csv-file data/historical_pl.csv
  ```
  - Review category overrides in `config/materiality_thresholds_empirical.yaml`
  - Enable empirical thresholds: `use_empirical: true` in `materiality_config.yaml`

## Analysis Execution

- [ ] **Run P&L Analysis Workflow**
  ```bash
  python test_efficient_workflow.py
  ```
  - Verify completion without errors
  - Check execution time (target: <60s per cost center)
  - Review phase logs for warnings

- [ ] **Review Outputs**
  - **JSON**: `outputs/cost_center_*.json` - for data validation
  - **Markdown**: `outputs/cost_center_*.md` - for executive review

## Analysis Review

### Executive Summary Review
- [ ] Total variance aligns with expectations
- [ ] Top drivers make business sense
- [ ] Key actions are specific and actionable

### Variance Drivers Review
- [ ] High materiality items investigated
- [ ] Drill-down reasoning is logical
- [ ] GL-level details support conclusions

### Alert Review
- [ ] Critical/High severity alerts reviewed
- [ ] Suppression rules working correctly
- [ ] No unexpected false positives

### Data Quality Check
- [ ] Missing ops metrics documented
- [ ] Data completeness acceptable
- [ ] Any data issues flagged for IT

## Stakeholder Review Meeting

- [ ] **Prepare Executive Summary**
  - Print or share Markdown report
  - Highlight top 3 variances
  - Prepare backup details for questions

- [ ] **Review with Business Owners**
  - Revenue variances → Sales Leader
  - Cost variances → Operations Manager
  - Toll opportunities → Billing Specialist
  - Labor variances → HR Business Partner

- [ ] **Document Decisions**
  - Root causes validated by stakeholders
  - Action owners assigned
  - Follow-up dates established
  - One-time vs recurring classifications

## Post-Review Context Update

- [ ] **Update Business Context**
  ```bash
  python scripts/update_business_context.py --cost-center 067 --period 2025-09
  ```
  
  For each flagged variance:
  - [ ] Document validated root cause
  - [ ] Set follow-up action and status
  - [ ] Add to known patterns if recurring
  - [ ] Create suppression rule if timing issue

- [ ] **Update Action Ownership** (as needed)
  - [ ] Add new owners for specific accounts
  - [ ] Update SLAs based on lessons learned
  - [ ] Document any org structure changes

## Action Item Tracking

- [ ] **Create Action Items in System**
  - Revenue recovery opportunities
  - Cost reduction initiatives
  - Toll billing recoveries (within 180 days)
  - Process improvement tasks

- [ ] **Set Reminders**
  - Follow-up dates in calendar
  - SLA tracking for critical items
  - Escalation notifications configured

## Month-End Closeout

- [ ] **Archive Outputs**
  ```bash
  mkdir outputs/archive/2025-09
  mv outputs/cost_center_*.json outputs/archive/2025-09/
  mv outputs/cost_center_*.md outputs/archive/2025-09/
  ```

- [ ] **Commit Configuration Updates**
  ```bash
  git add config/business_context.yaml config/action_ownership.yaml
  git commit -m "Update business context for 2025-09 review"
  git push
  ```

- [ ] **Update Documentation** (if process changed)
  - New suppression rule patterns
  - Ownership routing changes
  - Threshold adjustments

- [ ] **Generate Month-End Report**
  - Summary of variances explained
  - Open action items count
  - Data quality issues resolved
  - Process improvements implemented

## Quarterly Reviews

- [ ] **Q1, Q2, Q3, Q4 - Regenerate Materiality Thresholds**
  ```bash
  python scripts/calculate_materiality_thresholds.py --data-source csv --csv-file data/historical_pl.csv
  ```

- [ ] **Review Suppression Rules**
  - Deactivate obsolete rules
  - Update descriptions for clarity
  - Adjust severity thresholds based on patterns

- [ ] **Chart of Accounts Audit**
  - Verify all new GLs have level mappings
  - Update canonical categories if structure changed
  - Clean up unused accounts

- [ ] **Ownership Matrix Review**
  - Confirm current owners and escalation paths
  - Update contact information
  - Review SLA performance

## Annual Reviews

- [ ] **Full Historical Analysis**
  - Trends over 12 months
  - Seasonal pattern validation
  - Materiality threshold effectiveness

- [ ] **Process Improvement Assessment**
  - Analysis execution time trends
  - False positive rate reduction
  - Stakeholder feedback summary

- [ ] **Configuration Cleanup**
  - Archive old root cause history (>24 months)
  - Remove expired patterns and suppressions
  - Update documentation for new hires

## Emergency Procedures

### Critical Alert Response
If a CRITICAL severity alert is generated:
1. Notify owner immediately (per `action_ownership.yaml`)
2. Escalate to management within SLA window
3. Document initial assessment in business context
4. Set follow-up check-in within 4 hours

### Data Quality Issues
If data completeness <80% or major discrepancies:
1. Halt analysis and notify IT/Data team
2. Document issue in analysis notes
3. Defer analysis until data is corrected
4. Update data quality thresholds if needed

### System Failures
If analysis execution fails or times out:
1. Check phase logs for error details
2. Verify data source connectivity
3. Validate chart and config files
4. Contact system admin if unresolved

## Tips for Efficiency

1. **Use Templates**: Save frequently used responses in business context
2. **Batch Updates**: Update context for multiple cost centers at once
3. **Automate Notifications**: Configure Teams/email webhooks in action_ownership.yaml
4. **Version Control**: Always commit config changes with descriptive messages
5. **Monthly Metrics**: Track time spent on reviews to identify improvement areas

## Quick Reference Commands

```bash
# Full workflow
python test_efficient_workflow.py

# Validation
python scripts/validate_chart_of_accounts.py

# Threshold generation
python scripts/calculate_materiality_thresholds.py --data-source csv --csv-file data/historical_pl.csv

# Context update
python scripts/update_business_context.py --cost-center 067 --period 2025-09

# Archive outputs
mkdir outputs/archive/$(date +%Y-%m)
mv outputs/cost_center_*.* outputs/archive/$(date +%Y-%m)/

# Git commit
git add config/*.yaml
git commit -m "Update business context for $(date +%Y-%m) review"
git push
```

## Success Metrics

Track these monthly to measure improvement:
- **Analysis execution time**: Target <60s per cost center
- **False positive rate**: Target <20% of alerts
- **Time to explain variances**: Track reduction month-over-month
- **Action closure rate**: Track SLA compliance
- **Recurring issue resolution**: Measure pattern suppression effectiveness

## Support Contacts

- **System Issues**: IT/Data Team
- **Configuration Help**: Finance BP
- **Business Context Questions**: Finance Manager
- **Tool Development**: Engineering Team

---

**Last Updated**: 2025-10-30  
**Version**: 1.0  
**Owner**: Finance Team





