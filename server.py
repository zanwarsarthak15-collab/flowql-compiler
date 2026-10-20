"""
FlowQL Web Application Server.

FastAPI server exposing compilation and AI advisory endpoints,
while serving the static Google Material 3 frontend directly.
Single execution command: uvicorn server:app --reload
"""
import os
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from dslc.compiler import compile_flowql
from dslc.ai import explain_error, review_code
from dslc.csv_utils import CSVUploadManager

from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("flowql.server")

app = FastAPI(
    title="FlowQL Studio",
    description="Mini Compiler & AI Assistant for Tabular Data DSL",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time_and_log(request: Request, call_next):
    """Measures request execution time, attaches header, and logs request lifecycle."""
    start_time = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms:.2f}ms)")
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Sanitizes unexpected server errors so stack traces are never exposed to the client."""
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "An internal server error occurred while processing the request.",
            "code": "INTERNAL_SERVER_ERROR"
        }
    )


# Shared upload manager instance
upload_manager = CSVUploadManager()

# Request Models with payload size boundaries
class CompileRequest(BaseModel):
    source: str = Field(..., max_length=256 * 1024, description="FlowQL source code (max 256KB)")
    target: str = Field(default="python", max_length=32)
    optimize: bool = True
    upload_id: Optional[str] = Field(default=None, max_length=128)
    file_mappings: Optional[Dict[str, str]] = None


class ExplainRequest(BaseModel):
    error: Dict[str, Any]
    source: str = Field(..., max_length=256 * 1024)


class ReviewRequest(BaseModel):
    source: str = Field(..., max_length=256 * 1024)
    target_code: str = Field(..., max_length=512 * 1024)
    target_name: str = Field(default="Python", max_length=32)


@app.get("/health")
async def health_check():
    """Health check endpoint confirming server status."""
    return {"status": "ok", "service": "FlowQL"}


@app.post("/api/upload-csv")
async def api_upload_csv(file: UploadFile = File(...)):
    """
    Accepts a multipart CSV file upload:
    - Enforces .csv extension
    - Enforces maximum file size limit (10 MB)
    - Validates CSV structure, detects columns, and infers FlowQL types (num, str, bool)
    - Generates sanitized identifiers and preview rows
    - Stores file securely in data/uploads/ with unique upload_id
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing from upload request.")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail=f"Only CSV files (.csv) are supported. Received '{file.filename}'."
        )

    try:
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="File size exceeds maximum allowed limit of 10 MB."
            )

        meta = upload_manager.save_upload(content, file.filename)
        # Never expose internal filesystem paths to the client
        safe_meta = {k: v for k, v in meta.items() if k != "stored_path"}
        return safe_meta
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process uploaded CSV: {str(e)}")


@app.delete("/api/upload-csv/{upload_id}")
async def api_delete_upload(upload_id: str):
    """Safely removes an uploaded file by its unique upload ID."""
    success = upload_manager.delete_upload(upload_id)
    if not success:
        raise HTTPException(status_code=404, detail="Upload ID not found or already removed.")
    return {"success": True, "message": "Uploaded file removed successfully."}


@app.get("/api/uploads")
async def api_list_uploads():
    """Returns list of currently active uploaded datasets without internal file paths."""
    return {
        "uploads": [
            {k: v for k, v in m.items() if k != "stored_path"}
            for m in upload_manager.registry.values()
        ]
    }


@app.post("/api/compile")
def api_compile(req: CompileRequest):
    """
    Runs full compiler pipeline: Lexer -> Parser -> Semantic -> IR -> Optimizer -> CodeGen.
    Supports resolving uploaded CSV datasets via upload_id or file_mappings.
    Runs in thread pool to avoid blocking the asyncio event loop.
    """
    res = compile_flowql(
        source=req.source,
        target=req.target,
        optimize=req.optimize,
        upload_id=req.upload_id,
        file_mappings=req.file_mappings,
        upload_manager=upload_manager
    )
    # Ensure generated_code is explicitly present alongside target_code
    res["generated_code"] = res.get("target_code", "")
    return res


@app.post("/api/explain")
def api_explain(req: ExplainRequest):
    """
    Advisory error explanation with Google Gemini.
    Returns plain-English root cause, suggested fix snippet, and practical tip.
    Gracefully degrades if API key is not configured or offline.
    Runs in thread pool to avoid blocking the asyncio event loop.
    """
    explanation = explain_error(
        error_dict=req.error,
        source_code=req.source
    )
    return explanation


@app.post("/api/review")
def api_review(req: ReviewRequest):
    """
    Advisory code review with Google Gemini.
    Returns verdict and up to 3 optimization/safety tips.
    Runs in thread pool to avoid blocking the asyncio event loop.
    """
    review = review_code(
        source_code=req.source,
        target_code=req.target_code,
        target_name=req.target_name
    )
    return review


@app.get("/api/examples")
async def api_examples():
    """
    Loads all built-in example programs from disk to populate the frontend demo dropdown.
    """
    examples_list = []
    base_dir = Path(__file__).parent / "examples"

    valid_dir = base_dir / "valid"
    if valid_dir.exists():
        for f in sorted(valid_dir.glob("*.fql")):
            examples_list.append({
                "id": f.stem,
                "name": f.stem.replace("_", " ").title(),
                "category": "Valid Pipelines",
                "code": f.read_text(encoding="utf-8")
            })

    invalid_dir = base_dir / "invalid"
    if invalid_dir.exists():
        for f in sorted(invalid_dir.glob("*.fql")):
            examples_list.append({
                "id": f.stem,
                "name": f.stem.replace("_", " ").title(),
                "category": "Error Cases",
                "code": f.read_text(encoding="utf-8")
            })

    return {"examples": examples_list}


@app.get("/")
async def serve_index():
    """Serve the frontend SPA. Works both locally (web/) and on Vercel (public/)."""
    for candidate in ["public", "web"]:
        html_path = Path(__file__).resolve().parent / candidate / "index.html"
        if html_path.exists():
            return FileResponse(str(html_path))
    return {"status": "FlowQL API running — frontend not found"}


# Mount static files for local dev (StaticFiles at / serves CSS/JS; explicit GET / above takes priority)
for static_dir_name in ["public", "web"]:
    static_dir = Path(__file__).resolve().parent / static_dir_name
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
        break
