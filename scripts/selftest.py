"""Offline self-test of the deterministic engine — no API key required.

Feeds the reconciler the facts the extractor would produce from the synthetic
corpus (in manifest order) and asserts:
  - the cross-stream accident-date contradiction is caught into the changelog
  - the income correction supersedes the salary slip but preserves it in history
  - the name variant 'Ramesh K. Sharma' is NOT a contradiction
  - the KB verifier passes every MUST invariant
  - the petition arithmetic re-derives to 5,760,000 (loss) and 350,000 (medical)

Run: .venv/bin/python -m scripts.selftest
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import store, reconcile, verify_kb, verify_petition  # noqa: E402

# Facts as the extractor would emit them, per document (manifest order).
FIXTURE = [
    ("police/fir.txt", "police", "FIR", [
        {"field": "victim_name", "value": "Ramesh Kumar Sharma", "extraction_confidence": 0.98},
        {"field": "victim_age", "value": "34", "extraction_confidence": 0.97},
        {"field": "accident_date", "value": "2024-03-15", "extraction_confidence": 0.96},
        {"field": "accident_place", "value": "NH-48 near Kherki Daula toll plaza, Gurugram", "extraction_confidence": 0.95},
        {"field": "offending_vehicle", "value": "Truck HR-55-K-9080", "extraction_confidence": 0.96},
        {"field": "offending_driver", "value": "Sat Pal", "extraction_confidence": 0.95},
        {"field": "vehicle_owner", "value": "M/s Sharma Transport Co.", "extraction_confidence": 0.93},
        {"field": "insurer", "value": "United India Insurance Co. Ltd.", "extraction_confidence": 0.95},
        {"field": "policy_number", "value": "UII/2023/COMM/778421", "extraction_confidence": 0.95},
        {"field": "negligence", "value": "Truck driven rashly and negligently struck the motorcycle from behind", "extraction_confidence": 0.92},
        {"field": "injuries", "value": "Grievous injuries to right leg and head", "extraction_confidence": 0.9},
    ]),
    ("medical/discharge_summary.txt", "medical", "Discharge Summary", [
        {"field": "victim_name", "value": "Ramesh K. Sharma", "extraction_confidence": 0.96},
        {"field": "victim_age", "value": "34", "extraction_confidence": 0.97},
        {"field": "accident_date", "value": "2024-03-16", "extraction_confidence": 0.9},
        {"field": "injuries", "value": "Compound fracture of right femur; closed head injury", "extraction_confidence": 0.95},
        {"field": "hospitalization_days", "value": "18", "extraction_confidence": 0.96},
    ]),
    ("medical/disability_certificate.txt", "medical", "Disability Assessment Certificate", [
        {"field": "victim_name", "value": "Ramesh Kumar Sharma", "extraction_confidence": 0.97},
        {"field": "functional_disability_pct", "value": "40", "extraction_confidence": 0.97},
        {"field": "permanent_disability", "value": "Yes — permanent 40% disability of the right lower limb", "extraction_confidence": 0.95},
    ]),
    ("medical/hospital_bill.txt", "medical", "Hospital Bill", [
        {"field": "medical_expense_surgery", "value": "200000", "extraction_confidence": 0.97},
        {"field": "medical_expense_room", "value": "90000", "extraction_confidence": 0.97},
        {"field": "medical_expense_medicines", "value": "35000", "extraction_confidence": 0.97},
        {"field": "medical_expense_diagnostics", "value": "25000", "extraction_confidence": 0.97},
    ]),
    ("financial/salary_slip.txt", "financial", "Salary Slip", [
        {"field": "occupation", "value": "Software Engineer", "extraction_confidence": 0.95},
        {"field": "employment_type", "value": "salaried_permanent", "extraction_confidence": 0.95},
        {"field": "annual_income", "value": "540000", "extraction_confidence": 0.85},
    ]),
    ("financial/form16.txt", "financial", "Form 16", [
        {"field": "annual_income", "value": "600000", "extraction_confidence": 0.96},
        {"field": "employment_type", "value": "salaried_permanent", "extraction_confidence": 0.95},
    ]),
]


def main() -> int:
    record = store.new_case_record("MACT-SELFTEST")
    all_results = []
    for source_doc, stream, source_type, raws in FIXTURE:
        for r in raws:
            r["stream"] = stream
            r["source_doc"] = source_doc
            r["source_type"] = source_type
        all_results.extend(reconcile.reconcile_facts(record, raws))

    failures = []

    def check(name, cond):
        print(("  PASS " if cond else "  FAIL ") + name)
        if not cond:
            failures.append(name)

    print("\n== reconciliation ==")
    contradictions = [r for r in all_results if r["classification"] == "contradiction"]
    check("exactly one contradiction caught", len(contradictions) == 1)
    check("contradiction is cross-stream", bool(contradictions) and contradictions[0]["cross_stream"])
    check("contradiction is on accident_date", bool(contradictions) and contradictions[0]["field"] == "accident_date")

    corrections = [r for r in all_results if r["classification"] == "correction"]
    check("exactly one correction (income)", len(corrections) == 1 and corrections[0]["field"] == "annual_income")
    income = store.find_active_by_field(record, "annual_income")
    check("active income is 600000", income and str(income["value"]) == "600000")
    check("prior income 540000 preserved in history",
          income and any(h["value"] == "540000" for h in income["history"]))

    name_results = [r for r in all_results if r["field"] == "victim_name"]
    check("victim_name has no contradiction (initial-aware match)",
          all(r["classification"] != "contradiction" for r in name_results))

    print("\n== KB invariants (deterministic) ==")
    verdict = verify_kb.run_deterministic(record)
    for c in verdict["must"]:
        check("%s %s" % (c["id"], c["note"][:60]), c["status"] == "PASS")
    check("KB verdict PASS", verdict["result"] == "PASS")

    print("\n== petition arithmetic (re-derived from KB) ==")
    rc = verify_petition.recompute(record)
    loss = rc["loss_of_future_earning"]
    med = rc["medical_expenses"]
    check("loss of future earning == 5,760,000", loss and loss["amount"] == 5760000)
    check("  multiplier 16 (age 34 band 31-35)", loss and loss["multiplier"] == 16)
    check("  future prospects +50%% (salaried <40)", loss and abs(loss["future_prospects_fraction"] - 0.50) < 1e-9)
    check("medical expenses == 350,000", med["amount"] == 350000)

    print("\n== changelog ==")
    contra_log = [e for e in record["changelog"] if e["action"] == "contradiction"]
    check("changelog records the contradiction", len(contra_log) == 1)
    print("\n  changelog.md preview:")
    print("  " + store.changelog_md_text(record).replace("\n", "\n  ")[:1200])

    print("\n%s" % ("ALL CHECKS PASSED" if not failures else "FAILURES: %s" % failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
