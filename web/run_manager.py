"""Manage analysis pipeline runs as subprocesses."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

RUNS_FILE = Path(__file__).resolve().parent / "runs.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys as _sys
import platform as _platform

if _platform.system() == "Windows":
    PYTHON = str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")
else:
    PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python")


def _load_runs() -> list[dict]:
    if not RUNS_FILE.exists():
        return []
    try:
        with open(RUNS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_runs(runs: list[dict]) -> None:
    with open(RUNS_FILE, "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=2, default=str)


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _refresh_status(run: dict) -> dict:
    if run["status"] == "running" and run.get("pid"):
        if not _is_pid_alive(run["pid"]):
            # Process finished — check return code from log
            run["status"] = "completed"
            run["finished_at"] = datetime.utcnow().isoformat()
            # Check if run.log has error indicators
            log_path = Path(run["output_dir"]) / "run.log"
            if log_path.exists():
                log_tail = log_path.read_text(errors="replace")[-2000:]
                last_lines = log_tail.split("\n")[-10:]
                if "Analysis failed:" in log_tail or any("Traceback" in line for line in last_lines):
                    run["status"] = "failed"
                    # Extract last error line
                    for line in reversed(log_tail.splitlines()):
                        if line.strip() and not line.startswith("["):
                            run["error"] = line.strip()[:200]
                            break
    return run


def start_run(params: dict[str, Any]) -> dict:
    """Launch a pipeline run as a subprocess. Returns the run record."""
    run_id = str(uuid.uuid4())[:8]
    dataset_id = params["dataset_id"]
    metrics = params.get("metrics", [])
    hierarchy = params.get("hierarchy", "")
    max_drill_depth = params.get("max_drill_depth", 3)
    start_date = params.get("start_date", "")
    end_date = params.get("end_date", "")
    dataset_name = params.get("dataset_name", "analysis")
    analysis_focus = params.get("analysis_focus", [])
    custom_focus = params.get("custom_focus", "")
    hierarchy_levels = params.get("hierarchy_levels", [])
    hierarchy_filters = params.get("hierarchy_filters", {})

    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^a-z0-9_-]", "", dataset_name.replace(" ", "_").lower())
    output_dir = str(PROJECT_ROOT / "outputs" / safe_name / timestamp)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Build environment
    env = os.environ.copy()
    if metrics:
        env["DATA_ANALYST_METRICS"] = ",".join(metrics)
    if hierarchy:
        env["DATA_ANALYST_HIERARCHY"] = hierarchy
    if max_drill_depth:
        env["DATA_ANALYST_MAX_DRILL_DEPTH"] = str(max_drill_depth)
    if start_date:
        env["DATA_ANALYST_START_DATE"] = start_date
    if end_date:
        env["DATA_ANALYST_END_DATE"] = end_date
    if analysis_focus:
        env["DATA_ANALYST_FOCUS"] = ",".join(analysis_focus)
    if custom_focus:
        env["DATA_ANALYST_CUSTOM_FOCUS"] = custom_focus
    if hierarchy_levels:
        env["DATA_ANALYST_HIERARCHY_LEVELS"] = ",".join(hierarchy_levels)
    if hierarchy_filters:
        env["DATA_ANALYST_HIERARCHY_FILTERS"] = json.dumps(hierarchy_filters)
    env["DATA_ANALYST_OUTPUT_DIR"] = output_dir
    env["ACTIVE_DATASET"] = dataset_id.split("/")[-1] if "/" in dataset_id else dataset_id

    # New parameters: period type and brief style
    period_type = params.get("period_type", "")
    if period_type:
        env["DATA_ANALYST_PERIOD_TYPE"] = period_type
    brief_style = params.get("brief_style", "ceo")
    if brief_style:
        env["EXECUTIVE_BRIEF_STYLE"] = brief_style

    # Build query with focus context
    metric_str = " and ".join(metrics) if metrics else "all metrics"
    focus_labels = {
        "recent_weekly_trends": "recent weekly trends",
        "recent_monthly_trends": "recent monthly trends",
        "anomaly_detection": "anomalies and unusual patterns",
        "revenue_gap_analysis": "revenue gaps, missed billing, and billing anomalies",
        "seasonal_patterns": "seasonal patterns and cyclical behavior",
        "yoy_comparison": "year-over-year comparisons and changes",
        "forecasting": "trend forecasting and projections",
        "outlier_investigation": "outlier investigation and root cause analysis",
    }
    focus_parts = [focus_labels.get(f, f.replace("_", " ")) for f in analysis_focus]
    focus_str = ""
    if focus_parts:
        focus_str = " Focus on: " + ", ".join(focus_parts) + "."
    if custom_focus:
        focus_str += f" Additional direction: {custom_focus}"
    query = f"Analyze {metric_str}.{focus_str}"

    # Launch subprocess
    log_path = Path(output_dir) / "run.log"
    log_file = open(log_path, "w", encoding="utf-8")

    proc = subprocess.Popen(
        [PYTHON, "-m", "data_analyst_agent.agent", query],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    run = {
        "id": run_id,
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "metrics": metrics,
        "hierarchy": hierarchy,
        "analysis_focus": analysis_focus,
        "custom_focus": custom_focus,
        "hierarchy_levels": hierarchy_levels,
        "hierarchy_filters": hierarchy_filters,
        "max_drill_depth": max_drill_depth,
        "start_date": start_date,
        "end_date": end_date,
        "status": "running",
        "pid": proc.pid,
        "output_dir": output_dir,
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "error": None,
    }

    runs = _load_runs()
    runs.insert(0, run)
    _save_runs(runs)
    return run


def get_run(run_id: str) -> dict | None:
    runs = _load_runs()
    for run in runs:
        if run["id"] == run_id:
            run = _refresh_status(run)
            _save_runs(runs)
            return run
    return None


def list_runs() -> list[dict]:
    runs = _load_runs()
    changed = False
    for run in runs:
        old_status = run["status"]
        _refresh_status(run)
        if run["status"] != old_status:
            changed = True
    if changed:
        _save_runs(runs)
    return runs


def get_run_outputs(run_id: str) -> list[dict]:
    run = get_run(run_id)
    if not run:
        return []
    output_dir = Path(run["output_dir"])
    if not output_dir.exists():
        return []

    files = []
    for f in sorted(output_dir.iterdir()):
        if f.is_file():
            category = "other"
            if "brief" in f.name.lower():
                category = "executive_brief"
            elif f.name.startswith("metric_"):
                category = "metric_report"
            elif "alert" in f.name.lower():
                category = "alerts"
            elif f.name == "run.log":
                category = "log"
            elif f.name.endswith(".json") and "cache" in f.name:
                category = "cache"

            files.append({
                "name": f.name,
                "category": category,
                "size": f.stat().st_size,
                "extension": f.suffix,
            })
    return files


def get_run_log(run_id: str, lines: int = 200) -> str:
    run = get_run(run_id)
    if not run:
        return ""
    log_path = Path(run["output_dir"]) / "run.log"
    if not log_path.exists():
        return ""
    content = log_path.read_text(errors="replace")
    all_lines = content.splitlines()
    return "\n".join(all_lines[-lines:])


def get_file_content(run_id: str, filename: str) -> tuple[str, str]:
    """Return (content, content_type) for a file in the run's output dir."""
    run = get_run(run_id)
    if not run:
        raise FileNotFoundError("Run not found")
    # Security: sanitize filename and ensure it stays inside output dir
    if ".." in filename or "/" in filename or "\\" in filename or os.sep in filename:
        raise FileNotFoundError("Invalid filename")
    output_dir = Path(run["output_dir"]).resolve()
    file_path = (output_dir / filename).resolve()
    try:
        file_path.relative_to(output_dir)
    except ValueError:
        raise FileNotFoundError("Invalid filename")
    if not file_path.exists():
        raise FileNotFoundError("File not found")

    if file_path.suffix == ".pdf":
        return file_path.read_bytes(), "application/pdf"  # type: ignore
    elif file_path.suffix == ".json":
        return file_path.read_text(errors="replace"), "application/json"
    elif file_path.suffix == ".md":
        return file_path.read_text(errors="replace"), "text/markdown"
    else:
        return file_path.read_text(errors="replace"), "text/plain"
