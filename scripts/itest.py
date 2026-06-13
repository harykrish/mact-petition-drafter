"""Integration test of the pipeline + SSE event wiring WITHOUT an API key.

Stubs the four LLM calls with deterministic fakes, then drives
pipeline.run_full_events end-to-end and asserts the event sequence and the
committed artifacts. Validates everything except the live model calls.

Run: .venv/bin/python -m scripts.itest
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import llm, pipeline, store, config  # noqa: E402
from scripts.selftest import FIXTURE  # noqa: E402

# source_type -> extracted raws (without provenance; ingest attaches it)
_BY_TYPE = {st: raws for (_f, _s, st, raws) in FIXTURE}

CANNED_PETITION = """# IN THE MOTOR ACCIDENT CLAIMS TRIBUNAL AT GURUGRAM

Claim Petition under Section 166 of the Motor Vehicles Act, 1988.

Ramesh Kumar Sharma [F001] ... Claimant, versus Sat Pal (driver) [F006],
M/s Sharma Transport Co. (owner) [F007], United India Insurance Co. Ltd. [F008].

## Facts of the accident
On 2024-03-15 [F003] (note: hospital records state 2024-03-16 — minor discrepancy,
FIR date adopted) the claimant was struck by a rashly driven truck [F005].

## SCHEDULE OF COMPENSATION
| Head | Amount (INR) | Basis |
|------|-------------|-------|
| Loss of future earning capacity | 5760000 | [F? ] 600000 x 1.5 x 16 x 40% (Sarla Verma, Pranay Sethi) |
| Medical expenses | 350000 | itemised hospital bill |
| Pain and suffering | 100000 | Pranay Sethi conventional head |
| **TOTAL** | 6210000 | |
"""


def fake_extract_facts(doc_text, stream, source_doc, source_type):
    out = []
    for r in _BY_TYPE.get(source_type, []):
        out.append({"field": r["field"], "value": r["value"], "stream": stream,
                    "source_doc": source_doc, "source_type": source_type,
                    "extraction_confidence": r["extraction_confidence"]})
    return out


def fake_kb_grade(record):
    return {"result": "PASS", "must": [{"id": "I1", "status": "PASS", "note": "ok"}],
            "should": [], "blocking_failures": []}


def fake_draft_petition(record, feedback=None):
    return CANNED_PETITION


def fake_petition_grade(petition_md, record):
    # parse the loss figure actually present in the petition (so injection is caught)
    import re
    m = re.search(r"Loss of future earning capacity \| (\d+)", petition_md)
    claimed_loss = int(m.group(1)) if m else None
    m2 = re.search(r"Medical expenses \| (\d+)", petition_md)
    claimed_med = int(m2.group(1)) if m2 else None
    m3 = re.search(r"Pain and suffering \| (\d+)", petition_md)
    pain = int(m3.group(1)) if m3 else 0
    heads = {"Loss of future earning capacity": claimed_loss or 0,
             "Medical expenses": claimed_med or 0, "Pain and suffering": pain}
    return {"result": "pass",
            "must": [{"id": m, "status": "PASS", "note": "ok"} for m in
                     ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M11", "M12", "M13"]],
            "petition_claimed": {"loss_of_earning": claimed_loss, "medical_expenses": claimed_med,
                                 "heads": heads, "grand_total": sum(heads.values())}}


def run(inject):
    llm.extract_facts = fake_extract_facts
    llm.kb_grade = fake_kb_grade
    llm.draft_petition = fake_draft_petition
    llm.petition_grade = fake_petition_grade
    events = list(pipeline.run_full_events(use_llm=True, inject_error=inject))
    kinds = [k for k, _ in events]
    return events, kinds


def main():
    failures = []

    def check(name, cond):
        print(("  PASS " if cond else "  FAIL ") + name)
        if not cond:
            failures.append(name)

    print("\n== happy path ==")
    events, kinds = run(inject=False)
    check("6 ingest events", kinds.count("ingest") == 6)
    check("one kb_verify event", kinds.count("kb_verify") == 1)
    kb = dict(events)["kb_verify"] if False else [p for k, p in events if k == "kb_verify"][0]
    check("KB committed", kb["committed"] is True)
    da = [p for k, p in events if k == "draft_attempt"]
    check("petition passes on attempt 1", da and da[0]["result"] == "pass")
    check("done event present", "done" in kinds)
    check("case_record.json written", config.CASE_RECORD_PATH.exists())
    check("changelog.md written", config.CHANGELOG_MD_PATH.exists())
    check("petition_draft.md written", config.PETITION_PATH.exists())

    print("\n== injected-error path (verifier must catch & revise) ==")
    events, kinds = run(inject=True)
    da = [p for k, p in events if k == "draft_attempt"]
    check("first attempt was injected", da and da[0]["injected_error"])
    check("first attempt REVISE", da and da[0]["result"] == "revise")
    check("M8 failed on injected attempt", da and "M8" in da[0]["blocking_failures"])
    check("a later attempt passes", any(a["result"] == "pass" for a in da))

    # clean up artifacts written by the integration test
    for p in (config.CASE_RECORD_PATH, config.CHANGELOG_MD_PATH, config.PETITION_PATH):
        try:
            p.unlink()
        except FileNotFoundError:
            pass

    print("\n%s" % ("ALL INTEGRATION CHECKS PASSED" if not failures else "FAILURES: %s" % failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
