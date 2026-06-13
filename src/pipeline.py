"""Orchestrates the loop:

  ingest -> reconcile -> verify (fresh context) -> commit only on pass
  then: draft (KB only) -> verify (independent) -> revise on failure

Designed so the web app can drive each stage and animate the trace, and so a
CLI/self-test can run the whole thing at once.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from . import config, reconcile, store, verify_kb, verify_petition


# --- corpus helpers ------------------------------------------------------

def load_manifest() -> Dict:
    return json.loads((config.SYNTHETIC_DIR / "manifest.json").read_text(encoding="utf-8"))


def read_doc(rel_or_abs: str) -> str:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = config.SYNTHETIC_DIR / rel_or_abs
    return p.read_text(encoding="utf-8")


# --- ingest + reconcile one document ------------------------------------

def ingest_document(record: Dict, source_doc: str, stream: str, source_type: str,
                    doc_text: Optional[str] = None) -> Dict:
    """Extract facts from one document and reconcile them into `record`."""
    from . import llm  # imported lazily so non-LLM paths work without a key
    if doc_text is None:
        doc_text = read_doc(source_doc)
    stored_doc = _normalize_source(source_doc)
    raws = llm.extract_facts(doc_text, stream, stored_doc, source_type)
    results = reconcile.reconcile_facts(record, raws)
    return {
        "source_doc": stored_doc,
        "stream": stream,
        "source_type": source_type,
        "extracted": len(raws),
        "results": results,
    }


def _normalize_source(source_doc: str) -> str:
    """Stored provenance is unambiguous about synthetic vs real (data/)."""
    sd = str(source_doc).replace("\\", "/").lstrip("./")
    if sd.startswith("data/") or sd.startswith("synthetic/"):
        return sd
    return "synthetic/" + sd


def ingest_with_raws(record: Dict, source_doc: str, stream: str, source_type: str,
                     raws: List[Dict]) -> Dict:
    """Reconcile already-extracted facts (offline path / tests)."""
    for r in raws:
        r.setdefault("stream", stream)
        r.setdefault("source_doc", source_doc)
        r.setdefault("source_type", source_type)
    results = reconcile.reconcile_facts(record, raws)
    return {"source_doc": source_doc, "stream": stream, "source_type": source_type,
            "extracted": len(raws), "results": results}


# --- verify + commit -----------------------------------------------------

def verify_and_commit(record: Dict, use_llm: bool = True, commit_git: bool = False) -> Dict:
    """Verify the candidate KB. Persist to knowledge/ ONLY on pass."""
    verdict = verify_kb.verify(record, use_llm=use_llm)
    committed = False
    if verdict["result"] == "PASS":
        store.save_case_record(record)
        store.render_changelog_md(record)
        committed = True
        if commit_git:
            verdict["git"] = _git_commit_knowledge(record.get("case_id", "case"))
    return {"verdict": verdict, "committed": committed}


def _git_commit_knowledge(case_id: str) -> str:
    try:
        subprocess.run(["git", "add", "knowledge/case_record.json", "knowledge/changelog.md"],
                       cwd=str(config.BASE_DIR), check=True, capture_output=True)
        msg = "KB: commit verified case_record for %s" % case_id
        out = subprocess.run(["git", "commit", "-m", msg],
                             cwd=str(config.BASE_DIR), capture_output=True, text=True)
        return out.stdout.strip() or out.stderr.strip()
    except Exception as exc:  # best-effort only
        return "git commit skipped: %s" % exc


# --- draft + verify (with revise loop) ----------------------------------

def _inject_arithmetic_error(petition_md: str, record: Dict) -> str:
    """DEMO ONLY: corrupt the loss-of-earning figure so the verifier's
    independent re-derivation catches it and the loop revises. Clearly labelled."""
    rc = verify_petition.recompute(record)
    loss = rc.get("loss_of_future_earning")
    if not loss:
        return petition_md
    correct = str(loss["amount"])
    wrong = str(max(1, loss["amount"] - 1000000))
    if correct in petition_md:
        # replace only the first plain-integer occurrence (the schedule amount)
        petition_md = petition_md.replace(correct, wrong, 1)
        petition_md += ("\n\n<!-- DEMO: an arithmetic error was deliberately injected "
                        "into the loss-of-earning figure to demonstrate the verifier. -->")
    return petition_md


def draft_events(record: Dict, max_revisions: int = 2, use_llm: bool = True,
                 inject_error: bool = False):
    """Yield ('draft_attempt', attempt_dict) per try, then ('draft_done', summary)."""
    from . import llm
    attempts: List[Dict] = []
    feedback = None
    final_petition = ""
    passed = False
    for attempt in range(max_revisions + 1):
        petition = llm.draft_petition(record, feedback=feedback)
        injected = False
        if inject_error and attempt == 0:
            petition = _inject_arithmetic_error(petition, record)
            injected = petition.endswith("-->")
        report = verify_petition.verify(petition, record, use_llm=use_llm)
        att = {
            "attempt": attempt + 1,
            "injected_error": injected,
            "result": report["result"],
            "blocking_failures": report["blocking_failures"],
            "feedback_to_drafter": report["feedback_to_drafter"],
            "arithmetic": report["arithmetic"],
            "must": report["must"],
            "petition": petition,
        }
        attempts.append(att)
        final_petition = petition
        yield ("draft_attempt", att)
        if report["result"] == "pass":
            passed = True
            break
        feedback = report["feedback_to_drafter"]

    if final_petition:
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        config.PETITION_PATH.write_text(final_petition, encoding="utf-8")
    yield ("draft_done", {"passed": passed, "revisions": len(attempts) - 1,
                          "attempts": attempts, "final_petition": final_petition})


def draft_and_verify(record: Dict, max_revisions: int = 2, use_llm: bool = True,
                     inject_error: bool = False) -> Dict:
    summary = {}
    for kind, payload in draft_events(record, max_revisions, use_llm, inject_error):
        if kind == "draft_done":
            summary = payload
    return summary


# --- full run ------------------------------------------------------------

def run_full_events(use_llm: bool = True, commit_git: bool = False, inject_error: bool = False):
    """Drive the whole loop, yielding (event_type, payload) as each stage finishes.
    The web app wraps these as Server-Sent Events for a live demo."""
    manifest = load_manifest()
    record = store.new_case_record(manifest["case_id"])
    yield ("start", {"case_id": record["case_id"], "manifest": manifest})

    for idx, item in enumerate(manifest["ingest_order"]):
        trace = ingest_document(record, item["file"], item["stream"], item["source_type"])
        yield ("ingest", {"index": idx, "total": len(manifest["ingest_order"]),
                          "doc": trace, "record": record})

    commit = verify_and_commit(record, use_llm=use_llm, commit_git=commit_git)
    yield ("kb_verify", {"verdict": commit["verdict"], "committed": commit["committed"],
                         "record": record})

    if commit["committed"]:
        for kind, payload in draft_events(record, use_llm=use_llm, inject_error=inject_error):
            yield (kind, payload)

    yield ("done", {"record": record, "committed": commit["committed"]})


def run_full(use_llm: bool = True, commit_git: bool = False, inject_error: bool = False) -> Dict:
    out = {"ingest": [], "kb_verify": None, "committed": False, "draft": None, "record": None}
    for kind, payload in run_full_events(use_llm, commit_git, inject_error):
        if kind == "ingest":
            out["ingest"].append(payload["doc"])
        elif kind == "kb_verify":
            out["kb_verify"] = payload["verdict"]
            out["committed"] = payload["committed"]
        elif kind == "draft_done":
            out["draft"] = payload
        elif kind == "done":
            out["record"] = payload["record"]
            out["case_id"] = payload["record"]["case_id"]
    return out
