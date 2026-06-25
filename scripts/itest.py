"""Integration test of the pipeline + SSE event wiring WITHOUT an API key.

Stubs the four LLM calls with deterministic fakes, then drives
pipeline.run_full_events end-to-end and asserts the event sequence and the
committed artifacts. Validates everything except the live model calls.

Run: .venv/bin/python -m scripts.itest
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import llm, pipeline, config  # noqa: E402
from scripts.selftest import FIXTURE, EXPECTED_LOSS, EXPECTED_MEDICAL  # noqa: E402

# file -> extracted raws (keyed by file, since source_types repeat)
_BY_FILE = {f: raws for (f, _s, _st, raws) in FIXTURE}

_PAIN = 100000
_TOTAL = EXPECTED_LOSS + EXPECTED_MEDICAL + _PAIN

CANNED_PETITION = """# IN THE MOTOR ACCIDENT CLAIMS TRIBUNAL AT CHENGALPATTU

Claim Petition under Section 166 of the Motor Vehicles Act, 1988.

Vikram Anand Rao [F001] ... Claimant, versus Murugan (driver) [F006],
Sri Lakshmi Transports (owner) [F007], The Oriental Insurance Co. Ltd. [F008].

## Facts of the accident
On 2026-03-05 [F003] (hospital records state 2026-03-06 — discrepancy noted;
FIR date adopted) the claimant's car was struck by a rashly driven lorry [F005].

## SCHEDULE OF COMPENSATION
| Head | Amount (INR) | Basis |
|------|-------------|-------|
| Loss of future earning capacity | %d | 6500000 x 1.25 x 13 x 80%% (Sarla Verma, Pranay Sethi) |
| Medical expenses | %d | itemised hospital bill |
| Pain and suffering | %d | Pranay Sethi conventional head |
| **TOTAL** | %d | |
""" % (EXPECTED_LOSS, EXPECTED_MEDICAL, _PAIN, _TOTAL)


def fake_extract_facts(doc_text, stream, source_doc, source_type):
    for file, raws in _BY_FILE.items():
        if source_doc.endswith(file):
            return [{"field": r["field"], "value": r["value"], "stream": stream,
                     "source_doc": source_doc, "source_type": source_type,
                     "extraction_confidence": r["extraction_confidence"]} for r in raws]
    return []


def fake_kb_grade(record):
    return {"result": "PASS", "must": [{"id": "I1", "status": "PASS", "note": "ok"}],
            "should": [], "blocking_failures": []}


def fake_draft_petition(record, feedback=None):
    return CANNED_PETITION


def fake_petition_grade(petition_md, record):
    def grab(label):
        m = re.search(re.escape(label) + r" \| (\d+)", petition_md)
        return int(m.group(1)) if m else None
    loss, med, pain = grab("Loss of future earning capacity"), grab("Medical expenses"), grab("Pain and suffering")
    heads = {"Loss of future earning capacity": loss or 0, "Medical expenses": med or 0,
             "Pain and suffering": pain or 0}
    return {"result": "pass",
            "must": [{"id": m, "status": "PASS", "note": "ok"} for m in
                     ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M11", "M12", "M13"]],
            "petition_claimed": {"loss_of_earning": loss, "medical_expenses": med,
                                 "heads": heads, "grand_total": sum(heads.values())}}


def run(inject):
    llm.extract_facts = fake_extract_facts
    llm.kb_grade = fake_kb_grade
    llm.draft_petition = fake_draft_petition
    llm.petition_grade = fake_petition_grade
    return list(pipeline.run_full_events(use_llm=True, inject_error=inject))


def main():
    failures = []

    def check(name, cond):
        print(("  PASS " if cond else "  FAIL ") + name)
        if not cond:
            failures.append(name)

    print("\n== happy path ==")
    events = run(inject=False)
    kinds = [k for k, _ in events]
    check("9 ingest events", kinds.count("ingest") == 9)
    kb = [p for k, p in events if k == "kb_verify"][0]
    check("KB committed", kb["committed"] is True)
    da = [p for k, p in events if k == "draft_attempt"]
    check("petition passes on attempt 1", bool(da) and da[0]["result"] == "pass")
    check("loss re-derived to %d" % EXPECTED_LOSS,
          da and da[0]["arithmetic"]["recomputed"]["loss_of_future_earning"]["amount"] == EXPECTED_LOSS)
    check("done event present", "done" in kinds)
    check("case_record.json written", config.CASE_RECORD_PATH.exists())
    check("changelog.md written", config.CHANGELOG_MD_PATH.exists())
    check("petition_draft.md written", config.PETITION_PATH.exists())

    print("\n== injected-error path (verifier must catch & revise) ==")
    events = run(inject=True)
    da = [p for k, p in events if k == "draft_attempt"]
    check("first attempt was injected", bool(da) and da[0]["injected_error"])
    check("first attempt REVISE", bool(da) and da[0]["result"] == "revise")
    check("M8 failed on injected attempt", bool(da) and "M8" in da[0]["blocking_failures"])
    check("a later attempt passes", any(a["result"] == "pass" for a in da))

    for p in (config.CASE_RECORD_PATH, config.CHANGELOG_MD_PATH, config.PETITION_PATH):
        try:
            p.unlink()
        except FileNotFoundError:
            pass

    print("\n%s" % ("ALL INTEGRATION CHECKS PASSED" if not failures else "FAILURES: %s" % failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
