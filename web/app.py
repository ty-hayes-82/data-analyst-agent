"""Data Analyst Agent — Web UI."""
from __future__ import annotations

import os
import asyncio
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import contract_loader, run_manager

# Avoid noisy Windows Proactor shutdown assertions with active sockets.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

app = FastAPI(title="Data Analyst Agent", docs_url="/docs")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring and load balancers."""
    from datetime import datetime
    return {
        "status": "healthy",
        "service": "data-analyst-agent-web",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {
            "web_server": "ok"
        }
    }


@app.get("/api/version")
async def api_version():
    """Version information endpoint."""
    import sys
    from data_analyst_agent import __version__, __build__
    return {
        "version": __version__,
        "build": __build__,
        "python": sys.version
    }


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

    source_type = data_source.get("type", "csv")

    if source_type == "tableau_hyper":
        # Read from Tableau Hyper file
        try:
            import yaml
            loader_path = project_root / "config" / "datasets" / dataset_id / "loader.yaml"
            if loader_path.exists():
                loader_cfg = yaml.safe_load(loader_path.read_text())
                hyper_cfg = loader_cfg.get("hyper", {})
                tdsx_path = _Path(hyper_cfg.get("tdsx_path", ".")) / hyper_cfg.get("tdsx_file", "")
                if not tdsx_path.exists():
                    tdsx_path = project_root / hyper_cfg.get("tdsx_path", ".") / hyper_cfg.get("tdsx_file", "")
            else:
                tdsx_path = _Path(file_path)
                if not tdsx_path.is_absolute():
                    tdsx_path = project_root / file_path

            if not tdsx_path.exists():
                raise HTTPException(404, f"TDSX file not found: {tdsx_path}")

            import zipfile, tempfile
            from tableauhyperapi import HyperProcess, Telemetry, Connection, TableName

            with zipfile.ZipFile(str(tdsx_path)) as z:
                hyper_files = [f for f in z.namelist() if f.endswith(".hyper")]
                if not hyper_files:
                    raise HTTPException(500, "No .hyper file found in TDSX")
                tmp = tempfile.mkdtemp()
                z.extract(hyper_files[0], tmp)
                hyper_path = _Path(tmp) / hyper_files[0]

            import os
            os.makedirs("/tmp/hyper_logs_tableau", exist_ok=True)
            with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                              parameters={"log_dir": "/tmp/hyper_logs_tableau"}) as proc:
                with Connection(proc.endpoint, str(hyper_path)) as conn:
                    safe_col = column.replace('"', '""')
                    result = conn.execute_list_query(
                        f'SELECT DISTINCT "{safe_col}" FROM "Extract"."Extract" '
                        f'WHERE "{safe_col}" IS NOT NULL '
                        f'ORDER BY "{safe_col}" LIMIT 500'
                    )
                    values = [str(row[0]) for row in result if row[0] is not None]

            return {"column": column, "values": values, "total": len(values), "truncated": len(values) >= 500}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Failed to read Hyper dimension values: {str(e)}")
    else:
        # CSV path
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

# ---- Contract Editor APIs ----

@app.get("/api/datasets/{dataset_id:path}/contract/raw")
async def api_get_contract_raw(dataset_id: str):
    """Return raw contract YAML as text for editing."""
    try:
        contract = contract_loader.load_contract(dataset_id)
        return contract
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.put("/api/datasets/{dataset_id:path}/contract")
async def api_save_contract(dataset_id: str, req: Request):
    """Save updated contract YAML."""
    import re as _re
    import yaml
    from pathlib import Path as _Path

    if ".." in dataset_id:
        raise HTTPException(400, "Invalid dataset ID")

    body = await req.json()
    project_root = _Path(__file__).resolve().parent.parent
    contract_path = project_root / "config" / "datasets" / dataset_id / "contract.yaml"

    if not contract_path.parent.exists():
        contract_path.parent.mkdir(parents=True, exist_ok=True)

    # Backup existing
    if contract_path.exists():
        backup = contract_path.with_suffix(".yaml.bak")
        import shutil
        shutil.copy2(contract_path, backup)

    with open(contract_path, "w", encoding="utf-8") as f:
        yaml.dump(body, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return {"status": "ok", "path": str(contract_path)}


@app.get("/api/datasets/{dataset_id:path}/defaults")
async def api_get_defaults(dataset_id: str):
    """Get saved analysis defaults for a dataset."""
    import yaml
    from pathlib import Path as _Path
    project_root = _Path(__file__).resolve().parent.parent
    defaults_path = project_root / "config" / "datasets" / dataset_id / "defaults.yaml"
    if defaults_path.exists():
        with open(defaults_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@app.put("/api/datasets/{dataset_id:path}/defaults")
async def api_save_defaults(dataset_id: str, req: Request):
    """Save analysis defaults for a dataset."""
    import yaml
    from pathlib import Path as _Path
    body = await req.json()
    project_root = _Path(__file__).resolve().parent.parent
    defaults_path = project_root / "config" / "datasets" / dataset_id / "defaults.yaml"
    defaults_path.parent.mkdir(parents=True, exist_ok=True)
    with open(defaults_path, "w", encoding="utf-8") as f:
        yaml.dump(body, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return {"status": "ok"}


# ---- Data Profile API ----

@app.get("/api/datasets/{dataset_id:path}/profile")
async def api_data_profile(dataset_id: str, sample_size: int = 1000):
    """Sample data from the source and return a statistical profile."""
    try:
        contract = contract_loader.load_contract(dataset_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    data_source = contract.get("data_source", {})
    source_type = data_source.get("type", "csv")
    file_path = data_source.get("file", "")

    from pathlib import Path as _Path
    project_root = _Path(__file__).resolve().parent.parent

    try:
        import pandas as pd
        df = None

        if source_type == "tableau_hyper":
            import yaml
            loader_path = project_root / "config" / "datasets" / dataset_id / "loader.yaml"
            if loader_path.exists():
                loader_cfg = yaml.safe_load(loader_path.read_text())
                hyper_cfg = loader_cfg.get("hyper", {})
                tdsx_path = _Path(hyper_cfg.get("tdsx_path", ".")) / hyper_cfg.get("tdsx_file", "")
                if not tdsx_path.exists():
                    tdsx_path = project_root / hyper_cfg.get("tdsx_path", ".") / hyper_cfg.get("tdsx_file", "")
            else:
                tdsx_path = _Path(file_path) if _Path(file_path).is_absolute() else project_root / file_path

            import zipfile, tempfile, os
            from tableauhyperapi import HyperProcess, Telemetry, Connection
            os.makedirs("/tmp/hyper_logs_tableau", exist_ok=True)

            with zipfile.ZipFile(str(tdsx_path)) as z:
                hyper_files = [f for f in z.namelist() if f.endswith(".hyper")]
                tmp = tempfile.mkdtemp()
                z.extract(hyper_files[0], tmp)
                hyper_path = _Path(tmp) / hyper_files[0]

            with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                              parameters={"log_dir": "/tmp/hyper_logs_tableau"}) as proc:
                with Connection(proc.endpoint, str(hyper_path)) as conn:
                    result = conn.execute_list_query(
                        f'SELECT * FROM "Extract"."Extract" LIMIT {sample_size}'
                    )
                    table_def = conn.catalog.get_table_definition(
                        conn.catalog.get_table_names("Extract")[0]
                    )
                    columns = [str(c.name) for c in table_def.columns]
                    # Convert Hyper native types (Date, Timestamp) to strings
                    clean_rows = []
                    for row in result:
                        clean_rows.append([str(v) if v is not None and not isinstance(v, (int, float, str, bool)) else v for v in row])
                    df = pd.DataFrame(clean_rows, columns=columns)
        else:
            full_path = (project_root / file_path).resolve()
            if full_path.exists():
                df = pd.read_csv(str(full_path), nrows=sample_size)

        if df is None or df.empty:
            return {"error": "No data loaded"}

        import math

        def _safe_float(v):
            """Convert to JSON-safe float (None for NaN/inf)."""
            if v is None: return None
            try:
                f = float(v)
                if math.isnan(f) or math.isinf(f): return None
                return f
            except (ValueError, TypeError):
                return None

        # Build profile
        profile = {
            "row_count": len(df),
            "column_count": len(df.columns),
            "columns": [],
            "sample_rows": df.head(5).fillna("").astype(str).to_dict(orient="records"),
        }

        for col in df.columns:
            col_info = {
                "name": col,
                "dtype": str(df[col].dtype),
                "non_null": int(df[col].notna().sum()),
                "null_pct": _safe_float(round(df[col].isna().mean() * 100, 1)) or 0,
                "unique": int(df[col].nunique()),
            }
            if pd.api.types.is_numeric_dtype(df[col]):
                col_info["type"] = "numeric"
                col_info["min"] = _safe_float(df[col].min()) if df[col].notna().any() else None
                col_info["max"] = _safe_float(df[col].max()) if df[col].notna().any() else None
                col_info["mean"] = _safe_float(round(df[col].mean(), 2)) if df[col].notna().any() else None
                col_info["std"] = _safe_float(round(df[col].std(), 2)) if df[col].notna().any() else None
            else:
                col_info["type"] = "categorical"
                top_values = df[col].value_counts().head(10).to_dict()
                col_info["top_values"] = {str(k): int(v) for k, v in top_values.items()}

            profile["columns"].append(col_info)

        return profile

    except Exception as e:
        raise HTTPException(500, f"Profiling failed: {str(e)}")


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
    period_type: str = ""
    brief_style: str = "ceo"
    dimension_filters: dict[str, list[str]] = {}  # filter on any dimension, not just hierarchy


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
