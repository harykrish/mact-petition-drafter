"""Persist the case knowledge base to Supabase — the Cambrian shared KB.

Mirrors knowledge/case_record.json (facts[] / contradictions[] / changelog[])
to the cases/facts/contradictions/changelog tables defined in
supabase/cambrian_kb.sql. Uses the PostgREST data API (service key) only;
the DDL must be applied separately (it cannot run through this API).

Push is idempotent: rows upsert on (case_id, fact_ref|contra_ref|seq), so
re-running ingestion for a case overwrites cleanly.

Env (loaded from .env): SUPABASE_URL, SUPABASE_SERVICE_KEY.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import httpx

# --- env -----------------------------------------------------------------

def _load_env() -> None:
    """Minimal .env loader (no python-dotenv dependency)."""
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_env()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# map a fact's stream to the agent domain that primarily cares about it
STREAM_DOMAIN = {
    "medical": "medical",
    "police": "legal",
    "financial": "legal",
    "rehab": "rehab",
    "personal": "general",
    "other": "general",
}


def _headers(upsert: bool = False) -> Dict[str, str]:
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    if upsert:
        h["Prefer"] = "resolution=merge-duplicates,return=minimal"
    return h


def _url(path: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{path}"


def configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def ping() -> Dict:
    """Check connectivity + whether the KB tables exist yet."""
    out = {"url": SUPABASE_URL, "reachable": False, "tables": {}}
    if not configured():
        out["error"] = "SUPABASE_URL / SUPABASE_SERVICE_KEY not set"
        return out
    with httpx.Client(timeout=20) as c:
        for t in ("cases", "facts", "contradictions", "changelog", "documents"):
            try:
                r = c.get(_url(f"{t}?select=*&limit=0"), headers=_headers())
                out["reachable"] = True
                out["tables"][t] = "ok" if r.status_code < 300 else f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                out["tables"][t] = f"error: {e.__class__.__name__}"
    return out


# --- row mappers (record dict -> table row) ------------------------------

def _fact_row(case_id: str, f: Dict) -> Dict:
    stream = f.get("stream", "other")
    return {
        "case_id": case_id,
        "fact_ref": f["id"],
        "field": f.get("field"),
        "value": None if f.get("value") is None else str(f.get("value")),
        "stream": stream,
        "domain": f.get("domain") or STREAM_DOMAIN.get(stream, "general"),
        "source_doc": f.get("source_doc"),
        "source_type": f.get("source_type"),
        "extracted_on": f.get("extracted_on"),
        "confidence": f.get("confidence", 0.5),
        "extraction_confidence": f.get("extraction_confidence"),
        "needs_human_review": bool(f.get("needs_human_review", False)),
        "superseded": bool(f.get("superseded", False)),
        "history": f.get("history", []),
    }


def _contra_row(case_id: str, x: Dict) -> Dict:
    return {
        "case_id": case_id,
        "contra_ref": x["id"],
        "field": x.get("field"),
        "status": x.get("status", "unresolved"),
        "values": x.get("values", []),
        "resolution_note": x.get("resolution_note"),
    }


def _log_row(case_id: str, e: Dict) -> Dict:
    return {
        "case_id": case_id,
        "seq": e["seq"],
        "ts": e.get("timestamp"),
        "action": e.get("action"),
        "field": e.get("field"),
        "fact_ref": e.get("fact_id"),
        "contradiction_ref": e.get("contradiction_id"),
        "summary": e.get("summary"),
    }


# --- push / fetch --------------------------------------------------------

def push_record(record: Dict, title: Optional[str] = None) -> Dict:
    """Upsert a full case_record dict into Supabase. Returns row counts."""
    if not configured():
        raise RuntimeError("Supabase not configured (set SUPABASE_URL / SUPABASE_SERVICE_KEY)")
    case_id = record["case_id"]
    counts = {"facts": 0, "contradictions": 0, "changelog": 0}
    with httpx.Client(timeout=60) as c:
        c.post(_url("cases"), headers=_headers(upsert=True),
               json={"case_id": case_id, "title": title or record.get("title") or case_id,
                     "status": "active"}).raise_for_status()

        facts = [_fact_row(case_id, f) for f in record.get("facts", [])]
        if facts:
            c.post(_url("facts?on_conflict=case_id,fact_ref"),
                   headers=_headers(upsert=True), json=facts).raise_for_status()
            counts["facts"] = len(facts)

        contras = [_contra_row(case_id, x) for x in record.get("contradictions", [])]
        if contras:
            c.post(_url("contradictions?on_conflict=case_id,contra_ref"),
                   headers=_headers(upsert=True), json=contras).raise_for_status()
            counts["contradictions"] = len(contras)

        logs = [_log_row(case_id, e) for e in record.get("changelog", [])]
        if logs:
            c.post(_url("changelog?on_conflict=case_id,seq"),
                   headers=_headers(upsert=True), json=logs).raise_for_status()
            counts["changelog"] = len(logs)
    return counts


def list_cases() -> List[Dict]:
    if not configured():
        return []
    with httpx.Client(timeout=20) as c:
        r = c.get(_url("cases?select=*&order=updated_at.desc"), headers=_headers())
        return r.json() if r.status_code < 300 else []


def fetch_record(case_id: str) -> Dict:
    """Reconstruct a case_record dict from Supabase (for verifiers / UI parity)."""
    if not configured():
        raise RuntimeError("Supabase not configured")
    with httpx.Client(timeout=30) as c:
        facts = c.get(_url(f"facts?case_id=eq.{case_id}&select=*&order=fact_ref"),
                      headers=_headers()).json()
        contras = c.get(_url(f"contradictions?case_id=eq.{case_id}&select=*&order=contra_ref"),
                        headers=_headers()).json()
        logs = c.get(_url(f"changelog?case_id=eq.{case_id}&select=*&order=seq"),
                     headers=_headers()).json()
    return {
        "case_id": case_id,
        "facts": [{
            "id": f["fact_ref"], "field": f["field"], "value": f["value"],
            "stream": f["stream"], "domain": f.get("domain"),
            "source_doc": f["source_doc"], "source_type": f["source_type"],
            "extracted_on": f["extracted_on"], "confidence": f["confidence"],
            "extraction_confidence": f.get("extraction_confidence"),
            "needs_human_review": f["needs_human_review"], "superseded": f["superseded"],
            "history": f.get("history", []),
        } for f in facts],
        "contradictions": [{
            "id": x["contra_ref"], "field": x["field"], "status": x["status"],
            "values": x["values"], "resolution_note": x.get("resolution_note"),
        } for x in contras],
        "changelog": [{
            "seq": e["seq"], "timestamp": e["ts"], "action": e["action"],
            "field": e.get("field"), "fact_id": e.get("fact_ref"),
            "contradiction_id": e.get("contradiction_ref"), "summary": e.get("summary"),
        } for e in logs],
    }


if __name__ == "__main__":
    import json
    import sys
    if "--ping" in sys.argv:
        print(json.dumps(ping(), indent=2))
    elif "--push" in sys.argv:
        path = sys.argv[sys.argv.index("--push") + 1]
        rec = json.loads(Path(path).read_text())
        print(json.dumps(push_record(rec), indent=2))
    elif "--fetch" in sys.argv:
        cid = sys.argv[sys.argv.index("--fetch") + 1]
        print(json.dumps(fetch_record(cid), indent=2))
    else:
        print("usage: python -m src.supastore [--ping | --push record.json | --fetch CASE_ID]")
