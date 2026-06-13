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

def _resolve_path(source_doc: str) -> Path:
    p = Path(source_doc)
    if p.is_absolute():
        return p
    sd = str(source_doc).replace("\\", "/")
    if sd.startswith("data/") or sd.startswith("synthetic/"):
        return config.BASE_DIR / sd
    return config.SYNTHETIC_DIR / sd


def ingest_document(record: Dict, source_doc: str, stream: str, source_type: str,
                    doc_text: Optional[str] = None) -> Dict:
    """Extract facts from one document (any supported format) and reconcile them."""
    from . import llm  # imported lazily so non-LLM paths work without a key
    stored_doc = _normalize_source(source_doc)
    if doc_text is not None:
        raws = llm.extract_facts(doc_text, stream, stored_doc, source_type)
    else:
        path = _resolve_path(source_doc)
        ext = path.suffix.lower()
        if ext in llm.TEXT_EXTS:
            # plain text → the function the tests stub
            raws = llm.extract_facts(path.read_text(encoding="utf-8", errors="ignore"),
                                     stream, stored_doc, source_type)
        else:
            raws = llm.extract_facts_from_path(str(path), stream, stored_doc, source_type)
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


# --- real corpus (the user's actual /data/ documents) -------------------

_SOURCE_TYPE_HINTS = [
    ("fir", "FIR"), ("charge", "Charge Sheet"), ("intimation", "Police Intimation"),
    ("disab", "Disability Assessment Certificate"), ("discharge", "Discharge Summary"),
    ("summary", "Interim Summary"), ("dossier", "Interim Summary"), ("interim", "Interim Summary"),
    ("bill", "Hospital Bill"), ("invoice", "Hospital Bill"),
    ("mri", "Imaging Report"), ("ct", "Imaging Report"), ("scan", "Imaging Report"),
    ("xray", "Imaging Report"), ("x-ray", "Imaging Report"), ("ultrasound", "Imaging Report"),
    ("angio", "Imaging Report"), ("holter", "Imaging Report"), ("lab", "Lab Report"),
    ("itr", "ITR"), ("return", "ITR"), ("form16", "Form 16"), ("form 16", "Form 16"),
    ("salary", "Salary Slip"), ("payslip", "Salary Slip"),
]
_STREAM_DEFAULT_TYPE = {"police": "Police Document", "medical": "Medical Record",
                        "financial": "Financial Document"}
MAX_PDF_BYTES = 28 * 1024 * 1024


def _infer_source_type(filename: str, stream: str) -> str:
    name = filename.lower()
    for kw, t in _SOURCE_TYPE_HINTS:
        if kw in name:
            return t
    return _STREAM_DEFAULT_TYPE.get(stream, "Document")


def real_corpus_files(include_images: bool = True, streams=None, limit=None):
    """List ingestible files under data/<stream>/. Images are included by default
    (read via Opus vision-OCR; large ones are downscaled, never skipped for size)."""
    from . import llm
    out = []
    for stream in (streams or config.VALID_STREAMS):
        d = config.DATA_DIR / stream
        if not d.exists():
            continue
        for p in sorted(d.iterdir()):
            if not p.is_file() or p.name.startswith(".") or p.name == "_run":
                continue
            ext = p.suffix.lower()
            if ext not in llm.SUPPORTED_EXTS:
                continue
            if ext in llm.IMAGE_MEDIA and not include_images:
                continue
            if ext == ".pdf" and p.stat().st_size > MAX_PDF_BYTES:
                continue
            out.append({"path": str(p), "rel": "data/%s/%s" % (stream, p.name),
                        "stream": stream, "source_type": _infer_source_type(p.name, stream)})
    return out[:limit] if limit else out


def run_real_events(include_images: bool = True, use_llm: bool = True, streams=None, limit=None):
    """Run the loop on the user's REAL /data/ documents, writing every artifact to
    a gitignored directory (config.REAL_PATHS). Never touches the public knowledge/."""
    paths = config.REAL_PATHS
    files = real_corpus_files(include_images=include_images, streams=streams, limit=limit)
    record = store.new_case_record("MACT-REAL-" + store.now_iso()[:10])
    yield ("start", {"case_id": record["case_id"], "files": files, "output_dir": str(paths.case_record.parent)})
    for idx, f in enumerate(files):
        try:
            trace = ingest_document(record, f["rel"], f["stream"], f["source_type"])
        except Exception as exc:
            trace = {"source_doc": f["rel"], "stream": f["stream"], "source_type": f["source_type"],
                     "extracted": 0, "results": [], "error": str(exc)}
        yield ("ingest", {"index": idx, "total": len(files), "doc": trace, "record": record})
    commit = verify_and_commit(record, use_llm=use_llm, paths=paths)
    yield ("kb_verify", {"verdict": commit["verdict"], "committed": commit["committed"], "record": record})
    if commit["committed"]:
        for kind, payload in draft_events(record, use_llm=use_llm, paths=paths):
            yield (kind, payload)
    yield ("done", {"record": record, "committed": commit["committed"], "output_dir": str(paths.case_record.parent)})


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

def verify_and_commit(record: Dict, use_llm: bool = True, commit_git: bool = False,
                      paths=None) -> Dict:
    """Verify the candidate KB. Persist ONLY on pass, to the case's paths."""
    paths = paths or config.SYNTHETIC_PATHS
    verdict = verify_kb.verify(record, use_llm=use_llm, logs_dir=paths.logs_dir)
    committed = False
    if verdict["result"] == "PASS":
        store.save_case_record(record, paths.case_record)
        store.render_changelog_md(record, paths.changelog_md)
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
                 inject_error: bool = False, paths=None):
    """Yield ('draft_attempt', attempt_dict) per try, then ('draft_done', summary)."""
    from . import llm
    paths = paths or config.SYNTHETIC_PATHS
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
        report = verify_petition.verify(petition, record, use_llm=use_llm, logs_dir=paths.logs_dir)
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
        paths.petition.parent.mkdir(parents=True, exist_ok=True)
        paths.petition.write_text(final_petition, encoding="utf-8")
    yield ("draft_done", {"passed": passed, "revisions": len(attempts) - 1,
                          "attempts": attempts, "final_petition": final_petition})


def draft_and_verify(record: Dict, max_revisions: int = 2, use_llm: bool = True,
                     inject_error: bool = False, paths=None) -> Dict:
    summary = {}
    for kind, payload in draft_events(record, max_revisions, use_llm, inject_error, paths=paths):
        if kind == "draft_done":
            summary = payload
    return summary


# --- full run ------------------------------------------------------------

def run_full_events(use_llm: bool = True, commit_git: bool = False, inject_error: bool = False,
                    paths=None):
    """Drive the whole loop, yielding (event_type, payload) as each stage finishes.
    The web app wraps these as Server-Sent Events for a live demo.
    `paths` defaults to the public/synthetic locations."""
    paths = paths or config.SYNTHETIC_PATHS
    manifest = load_manifest()
    record = store.new_case_record(manifest["case_id"])
    yield ("start", {"case_id": record["case_id"], "manifest": manifest})

    for idx, item in enumerate(manifest["ingest_order"]):
        trace = ingest_document(record, item["file"], item["stream"], item["source_type"])
        yield ("ingest", {"index": idx, "total": len(manifest["ingest_order"]),
                          "doc": trace, "record": record})

    commit = verify_and_commit(record, use_llm=use_llm, commit_git=commit_git, paths=paths)
    yield ("kb_verify", {"verdict": commit["verdict"], "committed": commit["committed"],
                         "record": record})

    if commit["committed"]:
        for kind, payload in draft_events(record, use_llm=use_llm, inject_error=inject_error, paths=paths):
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
