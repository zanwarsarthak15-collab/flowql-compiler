"""
FlowQL Web Application Server.

FastAPI server exposing compilation and AI advisory endpoints,
while serving the static Google Material 3 frontend directly.
Single execution command: uvicorn server:app --reload
"""
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dslc.compiler import compile_flowql
from dslc.ai import explain_error, review_code

app = FastAPI(
    title="FlowQL Studio",
    description="Mini Compiler & AI Assistant for Tabular Data DSL",
    version="1.0.0"
)

# Request Models
class CompileRequest(BaseModel):
    source: str
    target: str = "python"
    optimize: bool = True


class ExplainRequest(BaseModel):
    error: Dict[str, Any]
    source: str


class ReviewRequest(BaseModel):
    source: str
    target_code: str
    target_name: str = "Python"


@app.get("/health")
async def health_check():
    """Health check endpoint confirming server status."""
    return {"status": "ok", "service": "FlowQL"}


@app.post("/api/compile")
async def api_compile(req: CompileRequest):
    """
    Runs full compiler pipeline: Lexer -> Parser -> Semantic -> IR -> Optimizer -> CodeGen.
    Returns tokens, AST, IR, generated target code, and any diagnostics.
    """
    res = compile_flowql(
        source=req.source,
        target=req.target,
        optimize=req.optimize
    )
    # Ensure generated_code is explicitly present alongside target_code
    res["generated_code"] = res.get("target_code", "")
    return res


@app.post("/api/explain")
async def api_explain(req: ExplainRequest):
    """
    Advisory error explanation with Google Gemini.
    Returns plain-English root cause, suggested fix snippet, and practical tip.
    Gracefully degrades if API key is not configured or offline.
    """
    explanation = explain_error(
        error_dict=req.error,
        source_code=req.source
    )
    return explanation


@app.post("/api/review")
async def api_review(req: ReviewRequest):
    """
    Advisory code review with Google Gemini.
    Returns verdict and up to 3 optimization/safety tips.
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


# Mount web directory as static root for Single-Page Application
web_dir = Path(__file__).parent / "web"
web_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")
