"""Data Analyst Agent — Web UI."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import contract_loader, run_manager

app = FastAPI(title="Data Analyst Agent", docs_url="/docs")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


# ---- Dataset / Contract APIs ----

@app.get("/api/datasets")
async def api_datasets():
    return contract_loader.list_datasets()


@app.get("/api/datasets/{dataset_id:path}/contract")
async def api_contract(dataset_id: str):
    try:
        return contract_loader.load_contract(dataset_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))




# ---- Dataset Auto-Detection APIs ----

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/api/datasets/detect")
async def api_detect_dataset(file: UploadFile = File(...)):
    """Upload a CSV and auto-detect its contract properties."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are supported")

    # Save uploaded file
    import re as _re
    safe_name = _re.sub(r"[^a-zA-Z0-9._-]", "_", file.filename)
    dest = UPLOAD_DIR / safe_name
    content = await file.read()
    if len(content) > 200 * 1024 * 1024:  # 200MB limit
        raise HTTPException(413, "File too large (max 200MB)")
    dest.write_bytes(content)

    try:
        from . import contract_detector
        result = contract_detector.detect_contract(str(dest))
        return result
    except Exception as e:
        raise HTTPException(500, f"Detection failed: {str(e)}")


class ConfirmContractRequest(BaseModel):
    contract: dict
    file_path: str  # original filename


@app.post("/api/datasets/confirm")
async def api_confirm_contract(req: ConfirmContractRequest):
    """Save a confirmed contract as a new dataset."""
    import re as _re
    from . import contract_detector as cd

    # Generate dataset ID from name
    dataset_id = _re.sub(r"[^a-z0-9_]", "", req.contract.get("name", "dataset").lower().replace(" ", "_"))
    if not dataset_id:
        dataset_id = "custom_dataset"

    # Ensure data_source file path points to uploads dir
    safe_name = _re.sub(r"[^a-zA-Z0-9._-]", "_", req.file_path)
    upload_path = str(UPLOAD_DIR / safe_name)
    req.contract["data_source"] = {"type": "csv", "file": upload_path}

    try:
        saved_path = cd.save_contract(req.contract, dataset_id)
        return {"status": "ok", "dataset_id": f"csv/{dataset_id}", "contract_path": saved_path}
    except Exception as e:
        raise HTTPException(500, f"Save failed: {str(e)}")




# ---- Dimension Values API ----

@app.get("/api/datasets/{dataset_id:path}/dimension-values/{column}")
async def api_dimension_values(dataset_id: str, column: str):
    """Return unique values for a dimension column in a dataset."""
    import re as _re
    if not _re.match(r'^[a-zA-Z0-9_]+$', column):
        raise HTTPException(400, "Invalid column name")
    try:
        contract = contract_loader.load_contract(dataset_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    valid_columns = {d["column"] for d in contract.get("dimensions", [])}
    if column not in valid_columns:
        raise HTTPException(400, f"Column '{column}' is not a dimension in this dataset")

    data_source = contract.get("data_source", {})
    file_path = data_source.get("file", "")
    if not file_path:
        raise HTTPException(400, "No data file configured for this dataset")

    from pathlib import Path as _Path
    project_root = _Path(__file__).resolve().parent.parent
    full_path = (project_root / file_path).resolve()
    if not full_path.exists():
        raise HTTPException(404, "Data file not found")

    try:
        import pandas as pd
        df = pd.read_csv(str(full_path), usecols=[column], dtype=str)
        values = sorted(df[column].dropna().unique().tolist())
        truncated = len(values) > 500
        if truncated:
            values = values[:500]
        return {"column": column, "values": values, "total": len(values), "truncated": truncated}
    except Exception as e:
        raise HTTPException(500, f"Failed to read dimension values: {str(e)}")

# ---- Run APIs ----

class RunRequest(BaseModel):
    dataset_id: str
    dataset_name: str = ""
    metrics: list[str] = []
    hierarchy: str = ""
    hierarchy_levels: list[str] = []
    hierarchy_filters: dict[str, list[str]] = {}
    analysis_focus: list[str] = []
    custom_focus: str = ""
    max_drill_depth: int = 3
    start_date: str = ""
    end_date: str = ""


@app.post("/api/runs")
async def api_start_run(req: RunRequest):
    run = run_manager.start_run(req.model_dump())
    return run


@app.get("/api/runs")
async def api_list_runs():
    return run_manager.list_runs()


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str):
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/api/runs/{run_id}/outputs")
async def api_run_outputs(run_id: str):
    return run_manager.get_run_outputs(run_id)


@app.get("/api/runs/{run_id}/log")
async def api_run_log(run_id: str, lines: int = 200):
    return PlainTextResponse(run_manager.get_run_log(run_id, lines))




@app.get("/api/runs/{run_id}/progress")
async def api_run_progress(run_id: str):
    """Parse run log to extract pipeline progress."""
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    from pathlib import Path as _Path
    log_path = _Path(run["output_dir"]) / "run.log"
    if not log_path.exists():
        return {"stages": [], "current_stage": None, "percent": 0, "status": run["status"]}

    log = log_path.read_text(errors="replace")

    # Known pipeline stages in order
    PIPELINE_STAGES = [
        {"key": "contract_loader", "label": "Loading Contract", "weight": 2},
        {"key": "cli_parameter_injector", "label": "Configuring Parameters", "weight": 1},
        {"key": "output_dir_initializer", "label": "Initializing Output", "weight": 1},
        {"key": "data_fetch_workflow", "label": "Fetching Data", "weight": 8},
        {"key": "analysis_context_initializer", "label": "Preparing Analysis Context", "weight": 5},
        {"key": "planner_agent", "label": "Planning Analysis", "weight": 3},
        {"key": "dynamic_parallel_analysis", "label": "Running Statistical & Hierarchy Analysis", "weight": 10},
        {"key": "narrative_agent", "label": "Generating Narrative", "weight": 20},
        {"key": "alert_scoring_coordinator", "label": "Scoring Alerts", "weight": 5},
        {"key": "report_synthesis_agent", "label": "Synthesizing Report", "weight": 25},
        {"key": "output_persistence_agent", "label": "Saving Results", "weight": 3},
        {"key": "weather_context_agent", "label": "Weather Context", "weight": 2},
        {"key": "executive_brief_agent", "label": "Writing Executive Brief", "weight": 25},
    ]

    stages = []
    current_stage = None
    total_weight = sum(s["weight"] for s in PIPELINE_STAGES)
    completed_weight = 0

    for stage in PIPELINE_STAGES:
        started = f">>> Starting agent: {stage['key']}" in log
        # Check for both exact match and timed_ prefix variant
        finished = (f"<<< Finished agent: {stage['key']}" in log or
                    f"<<< Finished agent: timed_{stage['key']}" in log or
                    f"<<< {stage['key']}" in log)

        # Extract duration if finished
        duration = None
        import re as _re
        dur_match = _re.search(rf"Finished agent: (?:timed_)?{_re.escape(stage['key'])}.*?Duration: ([\d.]+)s", log)
        if dur_match:
            duration = float(dur_match.group(1))
            finished = True

        status = "pending"
        if finished:
            status = "completed"
            completed_weight += stage["weight"]
        elif started:
            status = "running"
            current_stage = stage["key"]
            completed_weight += stage["weight"] * 0.5  # halfway credit

        stages.append({
            "key": stage["key"],
            "label": stage["label"],
            "status": status,
            "duration": duration,
        })

    percent = min(100, int((completed_weight / total_weight) * 100)) if total_weight else 0

    # If run completed, force 100%
    if run["status"] in ("completed", "failed"):
        percent = 100

    # Extract row counts and other useful info from log
    info = {}
    rows_match = _re.search(r"Loaded (\d[\d,]*) rows", log)
    if rows_match:
        info["rows_loaded"] = rows_match.group(1)
    filter_match = _re.search(r"Hierarchy filter.*?-> (\d+) rows", log)
    if filter_match:
        info["filtered_rows"] = filter_match.group(1)

    return {
        "stages": stages,
        "current_stage": current_stage,
        "percent": percent,
        "status": run["status"],
        "info": info,
    }

@app.get("/api/runs/{run_id}/files/{filename}")
async def api_run_file(run_id: str, filename: str):
    try:
        content, content_type = run_manager.get_file_content(run_id, filename)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    if isinstance(content, bytes):
        return Response(content=content, media_type=content_type)

    # For markdown, optionally render to HTML
    if content_type == "text/markdown":
        try:
            import markdown
            html = markdown.markdown(content, extensions=["tables", "fenced_code"])
            # Sanitize: strip script/iframe/object tags
            import re as _re
            html = _re.sub(r"<(script|iframe|object|embed|form|input)[^>]*>.*?</\1>", "", html, flags=_re.DOTALL | _re.IGNORECASE)
            html = _re.sub(r"<(script|iframe|object|embed|form|input)[^>]*/?>", "", html, flags=_re.IGNORECASE)
            return HTMLResponse(f"""<!doctype html><html><head>
                <style>body{{font-family:system-ui;max-width:800px;margin:2em auto;padding:0 1em;color:#e0e0e0;background:#1a1a2e}}
                table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #333;padding:6px 10px;text-align:left}}
                pre{{background:#0d1117;padding:1em;border-radius:4px;overflow-x:auto}}code{{color:#7ee787}}</style>
                </head><body>{html}</body></html>""")
        except ImportError:
            pass

    return PlainTextResponse(content)
