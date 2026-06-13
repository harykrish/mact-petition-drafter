"""Petition verifier — independent grader for the MACT petition draft.

Arithmetic (M8/M9/M10) is re-derived from the knowledge base in plain Python,
with no reference to what the drafter wrote — then compared to the amounts the
fresh-context LLM verifier parsed out of the petition. If the drafter fat-fingers
a multiplier or mis-sums the bills, the re-derived figure won't match and the
petition is sent back for revision.

Qualitative MUSTs (sourcing, traceability, disputed-fact handling, precedent,
facts-only) are graded by the LLM verifier in a fresh context.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config, precedent, store
from .reconcile import _to_number

# MUSTs the LLM verifier owns (everything except the three arithmetic ones).
LLM_MUSTS = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M11", "M12", "M13"]


def _int_field(record: Dict, field: str) -> Optional[int]:
    f = store.find_active_by_field(record, field)
    if f is None:
        return None
    n = _to_number(f["value"])
    return int(round(n)) if n is not None else None


def _str_field(record: Dict, field: str) -> Optional[str]:
    f = store.find_active_by_field(record, field)
    return str(f["value"]) if f else None


def _medical_items(record: Dict) -> List[Tuple[str, int]]:
    items = []
    for f in store.active_facts(record):
        if f["field"].startswith("medical_expense_"):
            n = _to_number(f["value"])
            if n is not None:
                items.append((f["field"].replace("medical_expense_", ""), int(round(n))))
    return sorted(items)


def recompute(record: Dict) -> Dict:
    """Independently derive the pecuniary heads from the KB."""
    age = _int_field(record, "victim_age")
    income = _int_field(record, "annual_income")
    disability = _int_field(record, "functional_disability_pct")
    employment = (_str_field(record, "employment_type") or "salaried_permanent").strip()
    out: Dict[str, object] = {"inputs": {
        "victim_age": age, "annual_income": income,
        "functional_disability_pct": disability, "employment_type": employment}}
    if None not in (age, income, disability):
        out["loss_of_future_earning"] = precedent.loss_of_future_earning(
            income, age, employment, disability)
    else:
        out["loss_of_future_earning"] = None
    out["medical_expenses"] = precedent.medical_expenses_total(_medical_items(record))
    return out


def _eq_amount(a, b) -> bool:
    na, nb = _to_number(a), _to_number(b)
    return na is not None and nb is not None and abs(na - nb) < 0.5


def verify(petition_md: str, record: Dict, use_llm: bool = True, write_log: bool = True,
           logs_dir=None) -> Dict:
    logs_dir = logs_dir or config.LOGS_DIR
    rc = recompute(record)
    must: List[Dict] = []
    feedback: List[str] = []

    # --- LLM qualitative + parse (fresh context) ---
    llm_result: Optional[Dict] = None
    claimed: Dict = {}
    if use_llm:
        try:
            from . import llm
            llm_result = llm.petition_grade(petition_md, record)
            claimed = llm_result.get("petition_claimed", {}) or {}
        except Exception as exc:
            llm_result = {"error": str(exc)}

    # --- M8: loss of future earning matches our re-derivation ---
    loss = rc.get("loss_of_future_earning")
    if loss is None:
        must.append({"id": "M8", "status": "FAIL", "note": "KB lacks age/income/disability to compute loss of earning"})
        feedback.append("M8: knowledge base is missing age/income/disability — cannot ground loss of earning.")
    else:
        claimed_loss = claimed.get("loss_of_earning")
        if claimed_loss is None:
            must.append({"id": "M8", "status": "FAIL", "note": "could not parse a loss-of-earning amount from the petition"})
            feedback.append("M8: state the loss of future earning explicitly in the schedule.")
        elif _eq_amount(claimed_loss, loss["amount"]):
            must.append({"id": "M8", "status": "PASS", "note": "loss of earning %d matches re-derivation (%s)" % (loss["amount"], loss["formula"])})
        else:
            must.append({"id": "M8", "status": "FAIL",
                         "note": "petition claims %s; re-derived %d (%s)" % (claimed_loss, loss["amount"], loss["formula"])})
            feedback.append("M8: loss of future earning should be %d, computed as %s. You wrote %s." % (
                loss["amount"], loss["formula"], claimed_loss))

    # --- M9: medical expenses == sum of itemised bills ---
    med = rc["medical_expenses"]
    claimed_med = claimed.get("medical_expenses")
    if claimed_med is None:
        must.append({"id": "M9", "status": "FAIL", "note": "could not parse a medical-expenses amount from the petition"})
        feedback.append("M9: state total medical expenses in the schedule.")
    elif _eq_amount(claimed_med, med["amount"]):
        must.append({"id": "M9", "status": "PASS", "note": "medical expenses %d matches sum of bills (%s)" % (med["amount"], med["formula"])})
    else:
        must.append({"id": "M9", "status": "FAIL",
                     "note": "petition claims %s; itemised bills sum to %d (%s)" % (claimed_med, med["amount"], med["formula"])})
        feedback.append("M9: medical expenses should be %d (%s). You wrote %s." % (med["amount"], med["formula"], claimed_med))

    # --- M10: grand total == sum of schedule line items ---
    heads = claimed.get("heads") or {}
    grand = claimed.get("grand_total")
    head_sum = sum(v for v in (_to_number(x) for x in heads.values()) if v is not None) if heads else None
    if grand is None or head_sum is None:
        must.append({"id": "M10", "status": "FAIL", "note": "could not parse the schedule heads/total from the petition"})
        feedback.append("M10: include a SCHEDULE OF COMPENSATION table with one row per head and a TOTAL row.")
    elif _eq_amount(grand, head_sum):
        must.append({"id": "M10", "status": "PASS", "note": "grand total %s == sum of heads %d" % (grand, int(head_sum))})
    else:
        must.append({"id": "M10", "status": "FAIL", "note": "grand total %s != sum of heads %d" % (grand, int(head_sum))})
        feedback.append("M10: the grand total (%s) does not equal the sum of the listed heads (%d)." % (grand, int(head_sum)))

    # --- qualitative MUSTs from the LLM verifier ---
    llm_must_status = {}
    if isinstance(llm_result, dict) and isinstance(llm_result.get("must"), list):
        for item in llm_result["must"]:
            if isinstance(item, dict) and item.get("id"):
                llm_must_status[item["id"]] = item.get("status", "FAIL")
    for mid in LLM_MUSTS:
        status = llm_must_status.get(mid)
        if status is None:
            # LLM didn't report it; treat as inconclusive -> non-blocking note, not a hard fail
            must.append({"id": mid, "status": "UNGRADED", "note": "LLM verifier did not report this item"})
        else:
            must.append({"id": mid, "status": status, "note": "graded by fresh-context LLM verifier"})
            if status == "FAIL":
                feedback.append("%s: failed LLM grading — see verifier notes." % mid)

    # LLM-reported feedback string, if any
    if isinstance(llm_result, dict) and llm_result.get("feedback_to_drafter"):
        feedback.append("Verifier: %s" % llm_result["feedback_to_drafter"])

    blocking = [c["id"] for c in must if c["status"] == "FAIL"]
    result = "pass" if not blocking else "revise"
    report = {
        "result": result,
        "arithmetic": {
            "recomputed": rc,
            "petition_claimed": claimed,
        },
        "must": must,
        "blocking_failures": blocking,
        "feedback_to_drafter": "\n".join(feedback) if feedback else "",
        "llm": llm_result,
    }
    if write_log:
        _write_log(report, logs_dir)
    return report


def _write_log(report: Dict, logs_dir) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = store.now_iso().replace(":", "").replace("-", "")
    path = logs_dir / ("petition_verify_%s.md" % ts)
    rc = report["arithmetic"]["recomputed"]
    loss = rc.get("loss_of_future_earning")
    med = rc.get("medical_expenses", {})
    lines = ["# Petition verification — %s" % store.now_iso(), "",
             "Result: **%s**" % report["result"], "",
             "## Independent arithmetic (re-derived from the KB)"]
    if loss:
        lines.append("- Loss of future earning: **%d** — %s" % (loss["amount"], loss["formula"]))
    lines.append("- Medical expenses: **%d** — %s" % (med.get("amount", 0), med.get("formula", "")))
    lines.append("- Petition claimed: `%s`" % json.dumps(report["arithmetic"]["petition_claimed"]))
    lines.append("")
    lines.append("## MUST")
    for c in report["must"]:
        mark = {"PASS": "x", "FAIL": " ", "UNGRADED": "~"}.get(c["status"], " ")
        lines.append("- [%s] **%s** (%s) — %s" % (mark, c["id"], c["status"], c["note"]))
    if report["feedback_to_drafter"]:
        lines.append("")
        lines.append("## Feedback to drafter")
        lines.append(report["feedback_to_drafter"])
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
