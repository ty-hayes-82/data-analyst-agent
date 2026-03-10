"""Data Analyst Agent — Web UI."""
from __future__ import annotations

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


# ---- Run APIs ----

class RunRequest(BaseModel):
    dataset_id: str
    dataset_name: str = ""
    metrics: list[str] = []
    hierarchy: str = ""
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
