"""Cambrian service API — lets the apps on top (NyayaSetu legal, Appa Speaks,
rehab, medical, coordination) consume the shared knowledge base over HTTP.

Auth: every endpoint requires header `X-API-Key` == env CAMBRIAN_API_KEY.
If CAMBRIAN_API_KEY is unset, the API is OPEN (dev mode) and logs a warning.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from . import config, pipeline, supastore

log = logging.getLogger("cambrian.api")
router = APIRouter(prefix="/api")


def require_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    expected = os.environ.get("CAMBRIAN_API_KEY")
    if not expected:
        log.warning("CAMBRIAN_API_KEY not set — Cambrian KB API is OPEN (dev mode).")
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


@router.get("/kb/cases")
def kb_cases(_=Depends(require_key)):
    """List every case in the knowledge base."""
    return supastore.list_cases()


@router.get("/kb/{case_id}")
def kb_case(case_id: str, _=Depends(require_key)):
    """Full KB bundle for one case: facts + contradictions + changelog + stats."""
    rec = supastore.fetch_record(case_id)
    facts = rec.get("facts", [])
    contradictions = rec.get("contradictions", [])
    by_stream: dict = {}
    for f in facts:
        by_stream[f["stream"]] = by_stream.get(f["stream"], 0) + 1
    stats = {
        "facts": len(facts),
        "active": len([f for f in facts if not f.get("superseded")]),
        "contradictions": len(contradictions),
        "needsReview": len([f for f in facts if f.get("needs_human_review")]),
        "byStream": by_stream,
    }
    case = next((c for c in supastore.list_cases() if c.get("case_id") == case_id),
                {"case_id": case_id})
    return {"case": case, "facts": facts, "contradictions": contradictions,
            "changelog": rec.get("changelog", []), "stats": stats}


@router.post("/petition/{case_id}")
def petition(case_id: str, _=Depends(require_key)):
    """Draft a MACT petition from the case KB and independently verify it
    (qualitative MUSTs + Python arithmetic re-derivation), revising on failure.
    Synchronous — makes several model calls, so it can take a while."""
    rec = supastore.fetch_record(case_id)
    if not rec.get("facts"):
        raise HTTPException(status_code=404, detail="no knowledge base for case %s" % case_id)
    summary = pipeline.draft_and_verify(rec, paths=config.REAL_PATHS)
    attempts = summary.get("attempts", [])
    last = attempts[-1] if attempts else {}
    return {
        "petition_md": summary.get("final_petition", ""),
        "passed": summary.get("passed", False),
        "revisions": summary.get("revisions", 0),
        "verdict": {
            "result": last.get("result"),
            "must": last.get("must", []),
            "arithmetic": last.get("arithmetic"),
            "blocking_failures": last.get("blocking_failures", []),
        },
    }
