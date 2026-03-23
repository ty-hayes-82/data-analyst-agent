# Dataset Configuration Directory

This directory contains the configuration files required for the data analysis pipeline to interface with different data sources. Datasets are organized by source type (`csv` or `tableau`).

## Standard Files per Dataset

Every dataset directory should contain a set of core configuration files that define its structure and how the system should process it.

### Core Files (Required for All)

1.  **`contract.yaml`**: The primary metadata definition for the dataset.
    *   **Purpose**: Defines metrics, dimensions, hierarchies, and materiality thresholds.
    *   **Key Sections**: `metrics`, `dimensions`, `grain`, `time`, `materiality`, and `reporting`.
    *   **Reporting Settings**:
        *   `reporting.max_drill_depth`: How many levels to drill down for this dataset.
        *   `reporting.executive_brief_drill_levels`: How many levels of scoped briefs to generate.
        *   `reporting.output_format`: The format of the final brief (`pdf`, `md`, or `both`).
2.  **`loader.yaml`**: Instructions for the data loading engine.
    *   **Purpose**: Maps physical source columns to the semantic names used in the `contract.yaml`.
    *   **Key Sections**: `source`, `column_mapping`, and `date_parsing`.

---

### CSV Datasets (`/csv/<dataset_name>/`)

Used for flat-file data sources.

*   **`<dataset_name>.csv`**: The raw data file.
*   **`loader.yaml`**: Includes CSV-specific settings like `delimiter`, `encoding`, and `melt` instructions if the data is in a wide format.
*   **`metric_units.yaml`** (Optional): Specific unit definitions for metrics.
*   **`ratio_metrics.yaml`** (Optional): Definitions for calculated ratios between metrics.

---

### Tableau Datasets (`/tableau/<dataset_name>/`)

Used for datasets sourced from Tableau Packaged Data Sources (`.tdsx`) or Hyper extracts.

*   **`.tdsx` files**: Store packaged sources under `data/tableau/` (see each dataset's `loader.yaml` `hyper.tdsx_path` / `hyper.tdsx_file`), not next to `contract.yaml`.
*   **`loader.yaml`**: Includes Tableau-specific settings like `tdsx_file`, `default_table`, and `aggregation` rules (since Hyper files are often at a much finer grain than required for analysis).
*   **`ratios.yaml`** or **`ratio_metrics.yaml`** (Optional): Definitions for ratios calculated post-aggregation.
*   **`derived_metrics.yaml`** (Optional): Definitions for metrics computed via SQL expressions during the Hyper fetch process.

## Directory Structure Example

```text
config/datasets/
├── csv/
│   └── toll_data/
│       ├── contract.yaml
│       ├── loader.yaml
│       └── toll_data.csv
└── tableau/
    └── ops_metrics_weekly/
        ├── contract.yaml
        ├── loader.yaml
        └── ratio_metrics.yaml

data/tableau/
└── Ops Metrics Weekly Scorecard.tdsx   # referenced by loader hyper.tdsx_*
```
