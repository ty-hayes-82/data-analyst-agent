# Data Analyst Agent

An intelligent financial and operational analysis agent built on Google's **Agent Development Kit (ADK)**. It provides automated variance analysis, root-cause identification, and actionable insights for logistics operations using a contract-driven semantic layer.

## 🚀 Overview

The Data Analyst Agent automates the complex process of analyzing Profit & Loss (P&L) data and operational metrics. It uses a recursive drill-down framework to navigate organizational hierarchies, identifying the specific drivers behind financial variances and presenting them as human-centric "Insight Cards."

## ✨ Key Features

- **📜 Contract-Driven Analysis**: Zero-code domain onboarding via YAML contracts that define metrics, hierarchies, and business policies.
- **🔄 Temporal Grain Awareness**: Automatically detects and adapts analysis narratives for **Weekly (WoW)** or **Monthly (MoM)** cadences.
- **📊 Recursive Drill-Down**: Level-agnostic analysis (e.g., Division → Region → Terminal → Driver) driven by dataset hierarchies.
- **⚡ Parallel Deep Analysis**: Specialized agents run in parallel to perform statistical, seasonal, ratio, and anomaly analysis.
- **🎙️ Executive Briefing**: Automatically synthesizes multi-metric findings into a concise, professional brief (Markdown, PDF, and HTML).
- **📉 Pre-summarization**: Uses a fast LLM to condense massive datasets before final synthesis, reducing context size by up to 90%.
- **🛠️ Flexible CLI**: Run targeted analysis for specific datasets, metrics, and dimensions with simple environment overrides.

## 🏗️ Architecture

```text
User Query → Target Extraction → Orchestration Pipeline:
  ├─ Data Fetch (Local Hyper or Remote A2A)
  ├─ Context Initialization (Semantic Layer Mapping)
  ├─ Recursive Drill-Down Loop (Level 0 → Level N):
  │   ├─ Hierarchy Variance Ranker (Aggregation)
  │   └─ Drill-Down Decision (LLM-driven)
  ├─ Parallel Analysis (Statistical, Seasonal, Ratio, Anomaly, etc.)
  ├─ Narrative Generation (Semantic Insight Cards)
  ├─ Report Synthesis (Optional Pre-summarization)
  └─ Output Persistence (Unique run-id directories)
```

## 🛠️ Quick Start

### 1. Installation

```bash
# Clone and navigate to the project
cd pl_analyst

# Setup virtual environment
python -m venv .venv
source .venv/bin/activate  # Or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Create a `.env` file in the root directory:

```bash
# LLM Configuration
GOOGLE_API_KEY=your_api_key_here

# Optional Overrides
TEMPORAL_GRAIN=weekly  # force weekly/monthly
DATA_ANALYST_MAX_DRILL_DEPTH=3
MAX_PARALLEL_METRICS=4
REPORT_SYNTHESIS_PRE_SUMMARIZE=true
```

### 3. Running Analysis

The agent is best executed as a module:

```bash
# Standard analysis for specific metrics and dimension
python -m data_analyst_agent --dataset ops_metrics \
  --metrics "Revenue xFuel,Truck Count,TRPM" \
  --dimension lob --dimension-value "Line Haul"
```

## 📜 Semantic Layer & Contracts

Dataset-specific logic is isolated in `pl_analyst/config/datasets/<dataset_name>/contract.yaml`.

### Example Contract Snippet
```yaml
name: "Ops Metrics"
time:
  column: "cal_dt"
  frequency: "weekly"
metrics:
  - name: "Revenue xFuel"
    column: "ttl_rev_amt"
    type: "additive"
hierarchies:
  - name: "regional_structure"
    levels: ["lob", "gl_rgn_nm", "gl_div_nm", "terminal"]
```

## 📂 Project Structure

- `pl_analyst/data_analyst_agent/`: Core agent orchestration and sub-agents.
- `pl_analyst/config/`: System-wide configurations and dataset contracts.
- `pl_analyst/outputs/`: Result directories organized by `timestamp_runid`.
- `pl_analyst/scripts/`: Utility scripts for data validation and testing.

## 📊 Outputs

Each run generates a unique directory under `outputs/` containing:
- `brief.md`: Consolidated executive summary.
- `brief.pdf / brief.html`: Professional formats for leadership.
- `metric_{name}.json`: Structured statistical results per metric.
- `metric_{name}.md`: Individual narrative reports per metric.
- `logs/execution.log`: Full trace of agent decisions and tool calls.

## ⚖️ License

Copyright 2025 Google LLC. Licensed under the Apache License, Version 2.0.
