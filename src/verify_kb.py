"""KB verifier. Grades a candidate case_record.json against
/rubric/kb_invariants.md.

Two independent graders:
  1. run_deterministic() — checks every invariant in code. Authoritative gate.
  2. llm_grade() (in llm.py) — a fresh-context Opus pass that re-reads the
     candidate + the rubric and returns its own verdict.

The commit gate requires the deterministic pass; the LLM verdict is logged
alongside as a cross-check. Both exchanges are written to /logs/.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from . import config, store


def _mk(checks: List[Dict], cid: str, ok: bool, note: str) -> None:
    checks.append({"id": cid, "status": "PASS" if ok else "FAIL", "note": note})


def _under_corpus(source_doc: str, stream: str) -> bool:
    sd = str(source_doc).replace("\\", "/").lstrip("./")
    # Accept data/<stream>/..., synthetic/<stream>/..., or a stream-relative path.
    for prefix in ("data/", "synthetic/", ""):
        if sd.startswith("%s%s/" % (prefix, stream)):
            return True
    return False


def run_deterministic(record: Dict) -> Dict:
    facts = record.get("facts", [])
    contradictions = record.get("contradictions", [])
    changelog = record.get("changelog", [])
    must: List[Dict] = []
    should: List[Dict] = []

    # I1 — complete provenance
    req = ("id", "field", "value", "stream", "source_doc", "source_type", "extracted_on")
    bad = [f.get("id") for f in facts
           if any(f.get(k) in (None, "") for k in req) or not isinstance(f.get("confidence"), (int, float))]
    _mk(must, "I1", not bad, "all facts have full provenance" if not bad else "missing provenance: %s" % bad)

    # I2 — valid stream
    bad = [f["id"] for f in facts if f.get("stream") not in config.VALID_STREAMS]
    _mk(must, "I2", not bad, "all streams valid" if not bad else "invalid stream: %s" % bad)

    # I3 — confidence range
    bad = [f["id"] for f in facts if not (0.0 <= float(f.get("confidence", -1)) <= 1.0)]
    _mk(must, "I3", not bad, "confidence in [0,1]" if not bad else "out of range: %s" % bad)

    # I4 — unique ids
    ids = [f["id"] for f in facts]
    _mk(must, "I4", len(ids) == len(set(ids)), "fact ids unique" if len(ids) == len(set(ids)) else "duplicate ids")

    # I5 — no silent overwrite: a corrected field keeps its prior value in history
    superseded_by_field: Dict[str, List[Dict]] = {}
    for f in facts:
        if f.get("superseded"):
            superseded_by_field.setdefault(f["field"], []).append(f)
    in_contradiction_ids = {v["fact_id"] for c in contradictions for v in c["values"]}
    i5_bad = []
    for field, supers in superseded_by_field.items():
        active = store.find_active_by_field(record, field)
        for s in supers:
            preserved = bool(s.get("history")) or s["id"] in in_contradiction_ids
            if active is not None:
                preserved = preserved or any(
                    h.get("value") == s["value"] for h in active.get("history", []))
            if not preserved:
                i5_bad.append(s["id"])
    _mk(must, "I5", not i5_bad,
        "corrections preserve prior values" if not i5_bad else "silent overwrite: %s" % i5_bad)

    # I6 — contradictions parked, not resolved
    i6_bad = [c.get("id") for c in contradictions
              if len(c.get("values", [])) < 2 or c.get("status") not in ("unresolved", "resolved")]
    _mk(must, "I6", not i6_bad,
        "%d contradiction(s) properly parked" % len(contradictions) if not i6_bad else "malformed: %s" % i6_bad)

    # I7 — review flag honest
    i7_bad = []
    for f in facts:
        should_flag = float(f.get("confidence", 1)) < config.NEEDS_REVIEW_BELOW or f["id"] in {
            v["fact_id"] for c in contradictions if c.get("status") == "unresolved" for v in c["values"]}
        if should_flag and not f.get("needs_human_review"):
            i7_bad.append(f["id"])
    _mk(must, "I7", not i7_bad, "review flags honest" if not i7_bad else "missing review flag: %s" % i7_bad)

    # I8 — append-only changelog + every mutation recorded
    seqs = [e.get("seq") for e in changelog]
    seq_ok = seqs == list(range(1, len(seqs) + 1))
    logged_facts = {e.get("fact_id") for e in changelog if e.get("fact_id")}
    logged_contra = {e.get("contradiction_id") for e in changelog if e.get("contradiction_id")}
    # A fact is "accounted for" if it's logged directly or recorded inside a
    # contradiction entry (whose own changelog line carries the contradiction_id).
    contra_fact_ids = {v.get("fact_id") for c in contradictions for v in c.get("values", [])}
    unlogged_f = [f["id"] for f in facts if f["id"] not in logged_facts and f["id"] not in contra_fact_ids]
    unlogged_c = [c["id"] for c in contradictions if c["id"] not in logged_contra]
    i8_ok = seq_ok and not unlogged_f and not unlogged_c
    _mk(must, "I8", i8_ok,
        "changelog monotonic; every mutation recorded" if i8_ok
        else "seq_ok=%s unlogged_facts=%s unlogged_contradictions=%s" % (seq_ok, unlogged_f, unlogged_c))

    # I9 — source within corpus, stream matches dir
    i9_bad = [f["id"] for f in facts if not _under_corpus(f.get("source_doc", ""), f.get("stream", ""))]
    _mk(must, "I9", not i9_bad, "sources within corpus" if not i9_bad else "out-of-corpus source: %s" % i9_bad)

    # I10 — referential integrity
    idset = set(ids)
    ref_bad = []
    for c in contradictions:
        for v in c.get("values", []):
            if v.get("fact_id") not in idset:
                ref_bad.append((c["id"], v.get("fact_id")))
    for e in changelog:
        if e.get("fact_id") and e["fact_id"] not in idset:
            ref_bad.append((e.get("seq"), e["fact_id"]))
    _mk(must, "I10", not ref_bad, "referential integrity holds" if not ref_bad else "dangling refs: %s" % ref_bad)

    # S1 — one active fact per scalar field (narrative + itemised costs exempt)
    from collections import Counter
    scalar_active = [f for f in store.active_facts(record)
                     if f["field"] not in config.NARRATIVE_FIELDS
                     and not f["field"].startswith("medical_expense_")]
    active_field_counts = Counter(f["field"] for f in scalar_active)
    multi = {k: n for k, n in active_field_counts.items() if n > 1}
    _mk(should, "S1", not multi, "one active fact per field" if not multi else "multiple active: %s" % multi)

    # S2 — resolution recorded
    s2_bad = [c["id"] for c in contradictions if c.get("status") == "resolved" and not c.get("resolution_note")]
    _mk(should, "S2", not s2_bad, "resolutions noted" if not s2_bad else "unnoted resolution: %s" % s2_bad)

    # S3 — monotonic history timestamps
    s3_bad = []
    for f in facts:
        ts = [h.get("extracted_on") for h in f.get("history", []) if h.get("extracted_on")]
        if ts != sorted(ts):
            s3_bad.append(f["id"])
    _mk(should, "S3", not s3_bad, "history timestamps ordered" if not s3_bad else "out of order: %s" % s3_bad)

    blocking = [c["id"] for c in must if c["status"] == "FAIL"]
    return {
        "result": "PASS" if not blocking else "FAIL",
        "must": must,
        "should": should,
        "blocking_failures": blocking,
    }


def verify(record: Dict, use_llm: bool = True, write_log: bool = True) -> Dict:
    """Run the deterministic gate and (optionally) the fresh-context LLM grader."""
    det = run_deterministic(record)
    llm_result = None
    if use_llm:
        try:
            from . import llm
            llm_result = llm.kb_grade(record)
        except Exception as exc:  # never let the LLM cross-check block the gate
            llm_result = {"error": str(exc)}

    combined = {
        "result": det["result"],          # deterministic gate is authoritative
        "deterministic": det,
        "llm": llm_result,
    }
    if write_log:
        _write_log(record, combined)
    return combined


def _write_log(record: Dict, result: Dict) -> None:
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = store.now_iso().replace(":", "").replace("-", "")
    path = config.LOGS_DIR / ("kb_verify_%s.md" % ts)
    det = result["deterministic"]
    lines = ["# KB verification — %s" % store.now_iso(),
             "",
             "Gate result (deterministic, authoritative): **%s**" % det["result"],
             "",
             "## MUST"]
    for c in det["must"]:
        lines.append("- [%s] **%s** — %s" % ("x" if c["status"] == "PASS" else " ", c["id"], c["note"]))
    lines.append("")
    lines.append("## SHOULD")
    for c in det["should"]:
        lines.append("- [%s] %s — %s" % ("x" if c["status"] == "PASS" else " ", c["id"], c["note"]))
    lines.append("")
    lines.append("## Independent LLM cross-check (fresh context)")
    lines.append("```json")
    lines.append(json.dumps(result.get("llm"), indent=2, ensure_ascii=False))
    lines.append("```")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
