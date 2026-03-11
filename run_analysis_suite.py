import os
import subprocess
import json
import time
import re
import shutil
from pathlib import Path
from datetime import datetime

# --- Configuration ---

INITIAL_RUNS = [
    {
        "id": "run_1",
        "dataset": "trade_data",
        "metrics": "trade_value_usd,volume_units",
        "dimension": "region",
        "description": "Trade Data (Weekly, Multi-metric)"
    },
    {
        "id": "run_2",
        "dataset": "covid_us_counties",
        "metrics": "cases,deaths",
        "dimension": "state",
        "description": "COVID US Counties (Daily, Minimize-direction)"
    },
    {
        "id": "run_3",
        "dataset": "owid_co2_emissions",
        "metrics": "co2,co2_per_capita,population",
        "description": "OWID CO2 Emissions (Yearly, Multi-metric)"
    },
    {
        "id": "run_4",
        "dataset": "global_temperature",
        "metrics": "temperature_anomaly",
        "description": "Global Temperature (Monthly, Single metric)"
    },
    {
        "id": "run_5",
        "dataset": "worldbank_population",
        "metrics": "population",
        "description": "World Bank Population (Yearly, Single metric)"
    },
    {
        "id": "run_6",
        "dataset": "toll_data",
        "metrics": "Toll Expense,Toll Revenue",
        "dimension": "shipper",
        "description": "Toll Data (Weekly, Hierarchical)"
    }
]

BASE_OUTPUT_DIR = Path("outputs/suite_runs")

def run_agent(config, cycle_dir):
    """Runs a single analysis and returns the results."""
    cmd = [
        "python", "-m", "data_analyst_agent",
        "--dataset", config["dataset"],
        "--metrics", config["metrics"]
    ]
    if config.get("dimension"):
        cmd.extend(["--dimension", config["dimension"]])
    
    print(f"Executing: {' '.join(cmd)}")
    start_time = time.time()
    
    # Run the command
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600 # 10 minutes timeout
    )
    
    duration = time.time() - start_time
    
    # Extract output directory from stdout/stderr
    combined_output = result.stdout + "\n" + result.stderr
    
    # Try multiple patterns
    output_dir = None
    patterns = [
        r"\[OutputDir\] Set DATA_ANALYST_OUTPUT_DIR=(.*)",
        r"Output\s+:\s+(.*)",
        r"Phase logger initialized\. Log file: (.*)\\logs\\execution\.log"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, combined_output)
        if match:
            output_dir = match.group(1).strip()
            break
    
    if not output_dir:
        print(f"Warning: Could not find output directory for run {config['id']}.")

    return {
        "id": config["id"],
        "dataset": config["dataset"],
        "command": " ".join(cmd),
        "exit_code": result.returncode,
        "duration_seconds": duration,
        "output_dir": output_dir,
        "stdout": result.stdout, # Full stdout for results.json
        "stderr": result.stderr
    }

def review_run(run_result):
    """Reviews the output of a run and returns a critique."""
    critique = {
        "id": run_result["id"],
        "status": "PASS" if run_result["exit_code"] == 0 else "FAIL",
        "issues": [],
        "artifacts": {}
    }
    
    if run_result["exit_code"] != 0:
        critique["issues"].append(f"Process failed with exit code {run_result['exit_code']}")
    
    output_path = run_result["output_dir"]
    if not output_path or not Path(output_path).exists():
        critique["issues"].append("Output directory not found or not created")
        critique["status"] = "FAIL"
        return critique

    output_path = Path(output_path)
    
    # Check for expected artifacts
    expected_files = ["brief.md"]
    # Metric files are named metric_{name}.json
    metrics = run_result["command"].split("--metrics ")[1].split(" ")[0].replace('"', '').split(",")
    for m in metrics:
        m_clean = m.strip().lower().replace(" ", "_").replace("/", "_")
        expected_files.append(f"metric_{m_clean}.json")

    for file_name in expected_files:
        file_path = output_path / file_name
        if file_path.exists():
            critique["artifacts"][file_name] = "EXISTS"
            if file_name.endswith(".json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        json.load(f)
                    critique["artifacts"][file_name] = "VALID_JSON"
                except Exception as e:
                    critique["artifacts"][file_name] = f"INVALID_JSON: {str(e)}"
                    critique["issues"].append(f"Invalid JSON in {file_name}")
            elif file_name == "brief.md":
                if file_path.stat().st_size > 0:
                    critique["artifacts"][file_name] = "NON_EMPTY"
                else:
                    critique["artifacts"][file_name] = "EMPTY"
                    critique["issues"].append("brief.md is empty")
        else:
            critique["artifacts"][file_name] = "MISSING"
            critique["issues"].append(f"Missing expected artifact: {file_name}")

    if critique["issues"]:
        critique["status"] = "WARN" if critique["status"] == "PASS" else "FAIL"

    return critique

def improve_config(config, critique):
    """Adjusts the config based on the critique."""
    improved = config.copy()
    improvements = []
    
    if critique["status"] == "FAIL":
        # If it failed, try to simplify
        metrics = config["metrics"].split(",")
        if len(metrics) > 1:
            improved["metrics"] = metrics[0]
            improvements.append(f"Simplified metrics from {config['metrics']} to {improved['metrics']}")
        elif config.get("dimension"):
            del improved["dimension"]
            improvements.append(f"Removed dimension filter: {config['dimension']}")
    elif critique["status"] == "WARN":
        # If it warned (e.g. missing artifacts), try to increase depth or change profile
        # For now, let's just log that we would improve it
        improvements.append("Detected issues in output, consider increasing drill depth or tuning LLM prompts (manual check recommended)")

    return improved, improvements

def run_cycle(cycle_number, configs):
    cycle_name = f"cycle_{cycle_number}"
    cycle_dir = BASE_OUTPUT_DIR / cycle_name
    cycle_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n--- Starting Cycle {cycle_number} ---")
    
    results = []
    critiques = []
    all_improvements = {}
    
    for config in configs:
        run_result = run_agent(config, cycle_dir)
        results.append(run_result)
        
        critique = review_run(run_result)
        critiques.append(critique)
        
        print(f"Run {config['id']} ({config['dataset']}): {critique['status']}")

    # Save results
    with open(cycle_dir / "results.json", "w", encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    
    # Generate critique.md
    with open(cycle_dir / "critique.md", "w", encoding='utf-8') as f:
        f.write(f"# Critique for Cycle {cycle_number}\n\n")
        for c in critiques:
            f.write(f"## {c['id']}\n")
            f.write(f"- **Status**: {c['status']}\n")
            if c['issues']:
                f.write("- **Issues**:\n")
                for issue in c['issues']:
                    f.write(f"  - {issue}\n")
            f.write("- **Artifacts**:\n")
            for art, status in c['artifacts'].items():
                f.write(f"  - `{art}`: {status}\n")
            f.write("\n")

    # Improve configs for next cycle
    next_configs = []
    for i, config in enumerate(configs):
        improved, improvements = improve_config(config, critiques[i])
        next_configs.append(improved)
        if improvements:
            all_improvements[config['id']] = improvements

    with open(cycle_dir / "improvements.json", "w", encoding='utf-8') as f:
        json.dump(all_improvements, f, indent=2)

    return next_configs, {
        "cycle": cycle_number,
        "passed": sum(1 for c in critiques if c['status'] == "PASS"),
        "warn": sum(1 for c in critiques if c['status'] == "WARN"),
        "failed": sum(1 for c in critiques if c['status'] == "FAIL"),
        "dir": str(cycle_dir)
    }

def main():
    if BASE_OUTPUT_DIR.exists():
        shutil.rmtree(BASE_OUTPUT_DIR)
    BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    configs = INITIAL_RUNS
    cycle_summaries = []
    
    for i in range(1, 4):
        configs, summary = run_cycle(i, configs)
        cycle_summaries.append(summary)

    # Final Summary
    with open(BASE_OUTPUT_DIR / "summary.md", "w", encoding='utf-8') as f:
        f.write("# Multi-Dataset Analysis Suite Summary\n\n")
        f.write("| Cycle | Passed | Warned | Failed | Directory |\n")
        f.write("|-------|--------|--------|--------|-----------|\n")
        for s in cycle_summaries:
            f.write(f"| {s['cycle']} | {s['passed']} | {s['warn']} | {s['failed']} | {s['dir']} |\n")
        
        f.write("\n## Conclusion\n")
        if cycle_summaries[-1]['failed'] == 0:
            f.write("All runs passed in the final cycle.")
        else:
            f.write(f"Final cycle still has {cycle_summaries[-1]['failed']} failures.")

    print("\n--- Suite Execution Complete ---")
    print(f"Summary written to {BASE_OUTPUT_DIR / 'summary.md'}")

if __name__ == "__main__":
    main()
