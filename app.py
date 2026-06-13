"""FastAPI app: serves the single-page demo and streams a live pipeline run.

Deployable as a single web service on Render or Railway:
    uvicorn app:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src import config, llm, pipeline, store

app = FastAPI(title="MACT Petition Drafter")

STATIC_DIR = config.BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/health")
def health():
    return {"model": config.MODEL, "api_key_present": llm.api_key_present()}


@app.get("/api/corpus")
def corpus():
    """The synthetic source documents, for display in the UI."""
    manifest = pipeline.load_manifest()
    docs = []
    for item in manifest["ingest_order"]:
        docs.append({
            "file": item["file"], "stream": item["stream"], "source_type": item["source_type"],
            "text": pipeline.read_doc(item["file"]),
        })
    return {"manifest": manifest, "docs": docs}


@app.get("/api/state")
def state():
    """The last committed artifacts, if any."""
    out = {"case_record": None, "changelog_md": None, "petition_md": None}
    if config.CASE_RECORD_PATH.exists():
        out["case_record"] = json.loads(config.CASE_RECORD_PATH.read_text(encoding="utf-8"))
    if config.CHANGELOG_MD_PATH.exists():
        out["changelog_md"] = config.CHANGELOG_MD_PATH.read_text(encoding="utf-8")
    if config.PETITION_PATH.exists():
        out["petition_md"] = config.PETITION_PATH.read_text(encoding="utf-8")
    return out


def _sse(use_llm: bool, inject_error: bool):
    def gen():
        try:
            for kind, payload in pipeline.run_full_events(use_llm=use_llm, inject_error=inject_error):
                yield "event: %s\ndata: %s\n\n" % (
                    kind, json.dumps(payload, ensure_ascii=False, default=str))
        except Exception as exc:  # surface errors to the client as an SSE event
            yield "event: error\ndata: %s\n\n" % json.dumps({"message": str(exc)})
    return gen


@app.get("/api/run-stream")
def run_stream(inject_error: int = 0, use_llm: int = 1):
    if not llm.api_key_present():
        return JSONResponse(
            status_code=400,
            content={"error": "ANTHROPIC_API_KEY is not set on the server. "
                              "Set it (Render/Railway dashboard or your shell) and retry."})
    return StreamingResponse(
        _sse(bool(use_llm), bool(inject_error))(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
