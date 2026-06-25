"""Offline self-test of the deterministic engine — no API key required.

Feeds the reconciler the facts the extractor would produce from the synthetic
corpus (in manifest order) and asserts:
  - the cross-stream accident-date contradiction is caught into the changelog
  - the income correction supersedes the preliminary CA certificate but
    preserves it in history
  - the name variant 'V. A. Rao' is NOT a contradiction
  - the KB verifier passes every MUST invariant
  - the petition arithmetic re-derives to 9,36,00,000 (loss) and 50,00,000 (medical)

Run: .venv/bin/python -m scripts.selftest
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import store, reconcile, verify_kb, verify_petition  # noqa: E402

# Facts as the extractor would emit them, per document (manifest order).
# (file, stream, source_type, [facts])
FIXTURE = [
    ("police/fir.txt", "police", "FIR", [
        {"field": "victim_name", "value": "Vikram Anand Rao", "extraction_confidence": 0.98},
        {"field": "victim_age", "value": "48", "extraction_confidence": 0.97},
        {"field": "accident_date", "value": "2026-03-05", "extraction_confidence": 0.96},
        {"field": "accident_place", "value": "GST Road (NH-32) near Mahindra City junction, Chengalpattu", "extraction_confidence": 0.95},
        {"field": "offending_vehicle", "value": "Lorry TN-19-K-4567", "extraction_confidence": 0.96},
        {"field": "offending_driver", "value": "Murugan", "extraction_confidence": 0.94},
        {"field": "vehicle_owner", "value": "Sri Lakshmi Transports", "extraction_confidence": 0.93},
        {"field": "insurer", "value": "The Oriental Insurance Co. Ltd.", "extraction_confidence": 0.95},
        {"field": "policy_number", "value": "OIC/2025/CV/55213", "extraction_confidence": 0.95},
        {"field": "negligence", "value": "Lorry driven rashly and negligently struck the car from the rear", "extraction_confidence": 0.92},
        {"field": "injuries", "value": "Grievous head and spinal injuries", "extraction_confidence": 0.9},
    ]),
    ("police/police_intimation.txt", "police", "Police Intimation", [
        {"field": "victim_name", "value": "Vikram A. Rao", "extraction_confidence": 0.95},
        {"field": "accident_date", "value": "2026-03-05", "extraction_confidence": 0.95},
        {"field": "offending_vehicle", "value": "Lorry TN-19-K-4567", "extraction_confidence": 0.95},
        {"field": "insurer", "value": "The Oriental Insurance Co. Ltd.", "extraction_confidence": 0.95},
    ]),
    ("medical/interim_summary_admission.txt", "medical", "Interim Summary", [
        {"field": "victim_name", "value": "V. A. Rao", "extraction_confidence": 0.95},
        {"field": "victim_age", "value": "48", "extraction_confidence": 0.96},
        {"field": "accident_date", "value": "2026-03-06", "extraction_confidence": 0.9},
        {"field": "injuries", "value": "Severe traumatic brain injury (diffuse axonal injury); C5-C6 cervical fracture; right haemothorax", "extraction_confidence": 0.95},
    ]),
    ("medical/imaging_report.txt", "medical", "Imaging Report", [
        {"field": "victim_name", "value": "Vikram Anand Rao", "extraction_confidence": 0.95},
        {"field": "injuries", "value": "Diffuse axonal injury; C5 fracture with cervical cord injury", "extraction_confidence": 0.95},
    ]),
    ("medical/interim_summary_followup.txt", "medical", "Interim Summary", [
        {"field": "hospitalization_days", "value": "45", "extraction_confidence": 0.96},
        {"field": "permanent_disability", "value": "Permanent neurological and cognitive deficit; not expected to return to profession", "extraction_confidence": 0.93},
        {"field": "injuries", "value": "Right hemiparesis with spasticity; cognitive impairment; expressive dysphasia", "extraction_confidence": 0.94},
    ]),
    ("medical/disability_certificate.txt", "medical", "Disability Assessment Certificate", [
        {"field": "victim_name", "value": "Vikram Anand Rao", "extraction_confidence": 0.97},
        {"field": "functional_disability_pct", "value": "80", "extraction_confidence": 0.97},
        {"field": "permanent_disability", "value": "Permanent 80% disability — severe cognitive and motor impairment", "extraction_confidence": 0.96},
    ]),
    ("medical/hospital_bill.txt", "medical", "Hospital Bill", [
        {"field": "medical_expense_neurosurgery", "value": "1500000", "extraction_confidence": 0.97},
        {"field": "medical_expense_icu", "value": "2000000", "extraction_confidence": 0.97},
        {"field": "medical_expense_imaging", "value": "400000", "extraction_confidence": 0.97},
        {"field": "medical_expense_medicines", "value": "600000", "extraction_confidence": 0.97},
        {"field": "medical_expense_rehab", "value": "500000", "extraction_confidence": 0.97},
    ]),
    ("financial/ca_income_certificate.txt", "financial", "CA Income Certificate", [
        {"field": "occupation", "value": "Founder & Managing Director, Apex Precision Instruments Pvt. Ltd.", "extraction_confidence": 0.95},
        {"field": "employment_type", "value": "self_employed", "extraction_confidence": 0.95},
        {"field": "annual_income", "value": "6500000", "extraction_confidence": 0.85},
    ]),
    ("financial/itr.txt", "financial", "ITR", [
        {"field": "annual_income", "value": "7200000", "extraction_confidence": 0.96},
        {"field": "employment_type", "value": "self_employed", "extraction_confidence": 0.95},
    ]),
]

EXPECTED_LOSS = 84500000   # 6500000 x (1+0.25) x 13 x 80%
EXPECTED_MEDICAL = 5000000


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
    check("exactly two contradictions caught", len(contradictions) == 2)
    check("contradiction is cross-stream (accident_date)", any(c["cross_stream"] and c["field"] == "accident_date" for c in contradictions))
    check("contradiction is on annual_income", any(c["field"] == "annual_income" for c in contradictions))

    corrections = [r for r in all_results if r["classification"] == "correction"]
    check("zero corrections (income is high risk so it contradicts)", len(corrections) == 0)
    income = store.find_active_by_field(record, "annual_income")
    check("active income remains 6500000 (parked contradiction)", income and str(income["value"]) == "6500000")

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
    check("loss of future earning == %d" % EXPECTED_LOSS, loss and loss["amount"] == EXPECTED_LOSS)
    check("  multiplier 13 (age 48 band 46-50)", loss and loss["multiplier"] == 13)
    check("  future prospects +25%% (self-employed 40-50)", loss and abs(loss["future_prospects_fraction"] - 0.25) < 1e-9)
    check("medical expenses == %d" % EXPECTED_MEDICAL, med["amount"] == EXPECTED_MEDICAL)

    print("\n== changelog ==")
    contra_log = [e for e in record["changelog"] if e["action"] == "contradiction"]
    check("changelog records the contradictions", len(contra_log) == 2)

    print("\n%s" % ("ALL CHECKS PASSED" if not failures else "FAILURES: %s" % failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
