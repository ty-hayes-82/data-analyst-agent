# Dataset Configuration Directory

This directory contains the configuration files required for the data analysis pipeline to interface with different data sources. Datasets are organized by source type (`csv` or `tableau`).

## Repository Organization: Config vs Data

This project maintains a strict separation between configuration (**intent**) and data (**payloads**).

| Location | Purpose | Examples |
|----------|---------|----------|
| **`config/`** | Versioned **intent**: how to load, map columns, define metrics/dimensions, thresholds, prompts, and experiments. | `contract.yaml`, `loader.yaml`, `agent_config.yaml`, `prompts/` |
| **`data/`** | **Payloads and tooling**: large or binary sources, validation CSVs, ad-hoc samples, and extraction scripts. | `data/tableau/*.tdsx`, `data/validation/*.csv`, `data/tableau/*.py` |

---

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

*   **`<dataset_name>.csv`**: Small, committed samples or CI datasets (optional).
*   **Large CSVs**: Should be stored under `data/datasets/<dataset_name>/` or `data/validation/` and referenced in `loader.yaml` `source.file`.
*   **`loader.yaml`**: Includes CSV-specific settings like `delimiter`, `encoding`, and `melt` instructions if the data is in a wide format.
*   **`metric_units.yaml`** (Optional): Specific unit definitions for metrics.
*   **`ratio_metrics.yaml`** (Optional): Definitions for calculated ratios between metrics.

---

### Tableau Datasets (`/tableau/<dataset_name>/`)

Used for datasets sourced from Tableau Packaged Data Sources (`.tdsx`) or Hyper extracts.

*   **`.tdsx` files**: Store packaged sources under `data/tableau/` (referenced by `hyper.tdsx_path` + `hyper.tdsx_file` in `loader.yaml`).
*   **`extracted/`**: Hyper extracts are staged under `data/tableau/extracted/<dataset_name>/` (configured via `hyper.extract_dir`).
*   **`loader.yaml`**: Includes Tableau-specific settings like `tdsx_file`, `default_table`, and `aggregation` rules.
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
└── extracted/
    └── ops_metrics_weekly/             # hyper extract output (gitignored)
```
