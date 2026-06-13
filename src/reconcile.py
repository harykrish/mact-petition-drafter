"""Reconcile incoming extracted facts against the knowledge base.

Each incoming fact is classified as one of:
  NEW          -> appended to facts[]
  CORRECTION   -> higher-authority value supersedes; prior value kept in history[]
  CONTRADICTION-> comparable-authority conflict; parked in contradictions[],
                  earlier fact stays provisionally active but flagged for review.
                  NEVER silently overwritten.
  DUPLICATE    -> same value (or name variant); discarded with a log entry.

A "RawFact" is a dict: {field, value, stream, source_doc, source_type,
extraction_confidence}. Provenance is set by the caller (the harness), never
trusted from the model.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from . import config, store


# --- value normalisation / equality -------------------------------------

def _to_number(value) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[^\d.\-]", "", value.replace(",", ""))
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_iso_date(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return "%s-%s-%s" % m.groups()
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", v)
    if m:
        d, mo, y = m.groups()
        return "%s-%02d-%02d" % (y, int(mo), int(d))
    return v.lower()


def _name_tokens(value: str) -> List[str]:
    return [t for t in re.split(r"[^\w]+", str(value).lower()) if t]


def _names_match(a: str, b: str) -> bool:
    """Initial-aware: 'ramesh k sharma' == 'ramesh kumar sharma'."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    return _ordered_token_match(ta, tb)


def _token_eq(x: str, y: str) -> bool:
    if x == y:
        return True
    if len(x) == 1 and y.startswith(x):
        return True
    if len(y) == 1 and x.startswith(y):
        return True
    return False


def _ordered_token_match(a: List[str], b: List[str]) -> bool:
    if len(a) != len(b):
        return _subseq_match(a, b) if len(a) < len(b) else _subseq_match(b, a)
    return all(_token_eq(x, y) for x, y in zip(a, b))


def _subseq_match(short_: List[str], long_: List[str]) -> bool:
    i = 0
    for tok in long_:
        if i < len(short_) and _token_eq(short_[i], tok):
            i += 1
    return i == len(short_)


def values_equal(field: str, v1, v2) -> bool:
    if field in config.NUMERIC_FIELDS:
        n1, n2 = _to_number(v1), _to_number(v2)
        return n1 is not None and n2 is not None and abs(n1 - n2) < 1e-9
    if field in config.DATE_FIELDS:
        return _to_iso_date(v1) == _to_iso_date(v2)
    if field in config.NAME_FIELDS:
        return _names_match(str(v1), str(v2))
    return str(v1).strip().lower() == str(v2).strip().lower()


def authority(source_type: str) -> float:
    return config.SOURCE_AUTHORITY.get(source_type, config.DEFAULT_AUTHORITY)


# --- fact construction ---------------------------------------------------

def _make_fact(record: Dict, raw: Dict) -> Dict:
    conf = round(authority(raw["source_type"]), 2)
    return {
        "id": store.next_fact_id(record),
        "field": raw["field"],
        "value": raw["value"],
        "stream": raw["stream"],
        "source_doc": raw["source_doc"],
        "source_type": raw["source_type"],
        "extracted_on": store.now_iso(),
        "confidence": conf,
        "extraction_confidence": round(float(raw.get("extraction_confidence", 0.9)), 2),
        "needs_human_review": conf < config.NEEDS_REVIEW_BELOW,
        "superseded": False,
        "history": [],
    }


def _history_entry(fact: Dict, reason: str) -> Dict:
    return {
        "value": fact["value"],
        "source_doc": fact["source_doc"],
        "source_type": fact["source_type"],
        "extracted_on": fact["extracted_on"],
        "reason_superseded": reason,
    }


# --- the classifier ------------------------------------------------------

def reconcile_fact(record: Dict, raw: Dict) -> Dict:
    """Apply one RawFact to the record. Returns the classification result."""
    field = raw["field"]

    # Narrative fields: corroborate or append; never a contradiction.
    if field in config.NARRATIVE_FIELDS:
        for af in store.active_facts(record):
            if af["field"] == field and values_equal(field, af["value"], raw["value"]):
                store.add_changelog(record, "duplicate",
                                    "Duplicate %s from %s corroborates %s" % (field, raw["source_type"], af["id"]),
                                    fact_id=af["id"], field=field)
                return {"classification": "duplicate", "fact_id": af["id"], "field": field}
        fact = _make_fact(record, raw)
        record["facts"].append(fact)
        store.add_changelog(record, "ingest_new",
                            "New %s (narrative) from %s" % (field, raw["source_type"]),
                            fact_id=fact["id"], field=field)
        return {"classification": "new", "fact_id": fact["id"], "field": field, "narrative": True}

    existing = store.find_active_by_field(record, field)

    if existing is None:
        fact = _make_fact(record, raw)
        record["facts"].append(fact)
        store.add_changelog(record, "ingest_new",
                            "New fact %s = %r from %s" % (field, fact["value"], raw["source_type"]),
                            fact_id=fact["id"], field=field)
        return {"classification": "new", "fact_id": fact["id"], "field": field}

    if values_equal(field, existing["value"], raw["value"]):
        store.add_changelog(record, "duplicate",
                            "Duplicate %s from %s corroborates %s" % (field, raw["source_type"], existing["id"]),
                            fact_id=existing["id"], field=field)
        return {"classification": "duplicate", "fact_id": existing["id"], "field": field}

    a_auth = existing["confidence"]
    f_auth = round(authority(raw["source_type"]), 2)

    # CORRECTION — incoming is clearly more authoritative.
    if f_auth - a_auth >= config.CORRECTION_MARGIN:
        new_fact = _make_fact(record, raw)
        new_fact["history"].append(_history_entry(
            existing, "Superseded by higher-authority %s (%s)" % (raw["source_type"], new_fact["id"])))
        existing["superseded"] = True
        record["facts"].append(new_fact)
        store.add_changelog(record, "correction",
                            "%s corrected %r -> %r (%s supersedes %s)" % (
                                field, existing["value"], new_fact["value"],
                                raw["source_type"], existing["source_type"]),
                            fact_id=new_fact["id"], field=field)
        return {"classification": "correction", "fact_id": new_fact["id"],
                "superseded": existing["id"], "field": field}

    # Incoming is clearly LESS authoritative — keep existing, archive incoming.
    if a_auth - f_auth >= config.CORRECTION_MARGIN:
        stale = _make_fact(record, raw)
        stale["superseded"] = True
        stale["history"].append(_history_entry(
            stale, "Lower authority than active %s; retained existing" % existing["id"]))
        record["facts"].append(stale)
        store.add_changelog(record, "correction_skipped",
                            "%s value %r from %s ignored; higher-authority %s (%s) retained" % (
                                field, stale["value"], raw["source_type"], existing["source_type"], existing["id"]),
                            fact_id=stale["id"], field=field)
        return {"classification": "correction_skipped", "fact_id": stale["id"],
                "kept": existing["id"], "field": field}

    # CONTRADICTION — comparable authority. Park it; never silently resolve.
    conflict = _make_fact(record, raw)
    conflict["superseded"] = True            # not used downstream as active...
    conflict["needs_human_review"] = True
    record["facts"].append(conflict)
    existing["needs_human_review"] = True    # ...but the active value is flagged disputed

    cid = store.next_contradiction_id(record)
    contradiction = {
        "id": cid,
        "field": field,
        "status": "unresolved",
        "resolution_note": None,
        "flagged_on": store.now_iso(),
        "values": [
            {"fact_id": existing["id"], "value": existing["value"], "stream": existing["stream"],
             "source_doc": existing["source_doc"], "source_type": existing["source_type"]},
            {"fact_id": conflict["id"], "value": conflict["value"], "stream": conflict["stream"],
             "source_doc": conflict["source_doc"], "source_type": conflict["source_type"]},
        ],
    }
    record["contradictions"].append(contradiction)
    cross = existing["stream"] != conflict["stream"]
    store.add_changelog(record, "contradiction",
                        "%s%s conflict: %s says %r (%s) vs %s says %r (%s) — parked for review" % (
                            "cross-stream " if cross else "",
                            field, existing["stream"], existing["value"], existing["source_type"],
                            conflict["stream"], conflict["value"], conflict["source_type"]),
                        contradiction_id=cid, field=field)
    return {"classification": "contradiction", "contradiction_id": cid,
            "fact_ids": [existing["id"], conflict["id"]], "cross_stream": cross, "field": field}


def reconcile_facts(record: Dict, raws: List[Dict]) -> List[Dict]:
    return [reconcile_fact(record, r) for r in raws]
