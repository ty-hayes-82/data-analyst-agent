# Tableau data files

Place Tableau packaged data sources (`.tdsx`) here. These files are not committed to git.

**Expected files** (from `config/datasets/tableau/`):

| Dataset           | File name                      |
|-------------------|--------------------------------|
| ops_metrics       | `Ops Metrics DS.tdsx`          |
| account_research  | `Account Research DS.tdsx`      |
| order_dispatch    | `Order Dispatch Revenue DS.tdsx` |

Set `ACTIVE_DATASET` or `config/agent_config.yaml` → `active_dataset` to one of: `ops_metrics`, `account_research`, `order_dispatch`.

You can copy these from the pl_analyst project or your Tableau exports.
