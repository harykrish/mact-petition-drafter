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


def _norm_id(v) -> str:
    toks = [t for t in re.split(r"[^a-z0-9]+", str(v).lower()) if t and t not in config.ID_NOISE_WORDS]
    return "".join(toks)


def values_equal(field: str, v1, v2) -> bool:
    if field in config.NUMERIC_FIELDS:
        n1, n2 = _to_number(v1), _to_number(v2)
        return n1 is not None and n2 is not None and abs(n1 - n2) < 1e-9
    if field in config.DATE_FIELDS:
        return _to_iso_date(v1) == _to_iso_date(v2)
    if field in config.NAME_FIELDS:
        return _names_match(str(v1), str(v2))
    if field in config.ID_FIELDS:
        return _norm_id(v1) == _norm_id(v2)
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

    # Stream ownership: ignore facts for an owned field from a non-owning stream.
    allowed = config.FIELD_STREAMS.get(field)
    if allowed is not None and raw["stream"] not in allowed:
        store.add_changelog(record, "skipped_off_stream",
                            "%s from %s ignored — established by the %s stream" % (
                                field, raw["stream"], "/".join(sorted(allowed))),
                            field=field)
        return {"classification": "skipped_off_stream", "field": field, "stream": raw["stream"]}

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
        a_auth = existing["confidence"]
        f_auth = round(authority(raw["source_type"]), 2)
        risk = config.get_field_risk(field)
        margin = config.RISK_MARGINS[risk]
        
        # If they fuzzy match but strings differ, take the higher authority one
        if existing["value"] != raw["value"] and f_auth > a_auth:
            new_fact = _make_fact(record, raw)
            new_fact["needs_human_review"] = False
            new_fact["history"] = list(existing.get("history", [])) + [_history_entry(
                existing, "Fuzzy match settled to higher-authority %s (%s)" % (raw["source_type"], new_fact["id"]))]
            existing["superseded"] = True
            record["facts"].append(new_fact)
            
            store.add_changelog(record, "fuzzy_settled",
                                f"{field} fuzzy matched {existing['value']!r} vs {raw['value']!r}. Settled to higher-authority {raw['source_type']} (weight {f_auth} > {a_auth}). Risk: {risk}, Threshold: {margin}",
                                fact_id=new_fact["id"], field=field)
            return {"classification": "fuzzy_settled", "fact_id": new_fact["id"], "superseded": existing["id"], "field": field}
        elif existing["value"] != raw["value"] and a_auth >= f_auth:
            stale = _make_fact(record, raw)
            stale["superseded"] = True
            stale["needs_human_review"] = False
            stale["history"].append(_history_entry(
                stale, "Fuzzy match; retained existing higher/equal authority %s" % existing["id"]))
            record["facts"].append(stale)
            existing["needs_human_review"] = False
            
            store.add_changelog(record, "fuzzy_settled_skipped",
                                f"{field} fuzzy matched {existing['value']!r} vs {raw['value']!r}. Retained higher/equal authority {existing['source_type']} (weight {a_auth} >= {f_auth}). Risk: {risk}, Threshold: {margin}",
                                fact_id=stale["id"], field=field)
            return {"classification": "fuzzy_settled_skipped", "fact_id": stale["id"], "kept": existing["id"], "field": field}

        store.add_changelog(record, "duplicate",
                            "Duplicate %s from %s corroborates %s" % (field, raw["source_type"], existing["id"]),
                            fact_id=existing["id"], field=field)
        return {"classification": "duplicate", "fact_id": existing["id"], "field": field}

    a_auth = existing["confidence"]
    f_auth = round(authority(raw["source_type"]), 2)
    risk = config.get_field_risk(field)
    margin = config.RISK_MARGINS[risk]

    # CORRECTION — incoming is clearly more authoritative.
    # (epsilon guards float subtraction, e.g. 0.95 - 0.85 == 0.0999...)
    if f_auth - a_auth >= margin - 1e-9:
        new_fact = _make_fact(record, raw)
        new_fact["needs_human_review"] = False
        # Carry forward the whole chain so the active fact's history holds every
        # prior value (keeps "no silent overwrite" true across repeated corrections).
        new_fact["history"] = list(existing.get("history", [])) + [_history_entry(
            existing, "Superseded by higher-authority %s (%s)" % (raw["source_type"], new_fact["id"]))]
        existing["superseded"] = True
        record["facts"].append(new_fact)
        store.add_changelog(record, "correction",
                            f"{field} corrected {existing['value']!r} -> {new_fact['value']!r} ({raw['source_type']} supersedes {existing['source_type']}). Risk: {risk}, Threshold: {margin}",
                            fact_id=new_fact["id"], field=field)
        return {"classification": "correction", "fact_id": new_fact["id"],
                "superseded": existing["id"], "field": field}

    # Incoming is clearly LESS authoritative — keep existing, archive incoming.
    if a_auth - f_auth >= margin - 1e-9:
        stale = _make_fact(record, raw)
        stale["superseded"] = True
        stale["needs_human_review"] = False
        stale["history"].append(_history_entry(
            stale, "Lower authority than active %s; retained existing" % existing["id"]))
        record["facts"].append(stale)
        existing["needs_human_review"] = False
        store.add_changelog(record, "correction_skipped",
                            f"{field} value {stale['value']!r} from {raw['source_type']} ignored; higher-authority {existing['source_type']} ({existing['id']}) retained. Risk: {risk}, Threshold: {margin}",
                            fact_id=stale["id"], field=field)
        return {"classification": "correction_skipped", "fact_id": stale["id"],
                "kept": existing["id"], "field": field}

    # CONTRADICTION — comparable authority. Park it; never silently resolve.
    existing["needs_human_review"] = True    # the active value is flagged disputed

    # Collapse into an existing unresolved contradiction on this field rather than
    # spawning a duplicate entry (e.g. several medical docs giving the same
    # alternate accident date). Decide BEFORE creating a fact so corroborating
    # values don't leave an orphaned superseded fact.
    existing_c = next((c for c in record["contradictions"]
                       if c["field"] == field and c.get("status") == "unresolved"), None)
    if existing_c is not None:
        if any(values_equal(field, v["value"], raw["value"]) for v in existing_c["values"]):
            store.add_changelog(record, "duplicate",
                                "%s value %r from %s corroborates contradiction %s" % (
                                    field, raw["value"], raw["source_type"], existing_c["id"]),
                                contradiction_id=existing_c["id"], field=field)
            return {"classification": "duplicate", "contradiction_id": existing_c["id"], "field": field}
        conflict = _make_fact(record, raw)
        conflict["superseded"] = True
        conflict["needs_human_review"] = True
        record["facts"].append(conflict)
        existing_c["values"].append({"fact_id": conflict["id"], "value": conflict["value"],
                                     "stream": conflict["stream"], "source_doc": conflict["source_doc"],
                                     "source_type": conflict["source_type"]})
        store.add_changelog(record, "contradiction",
                            "%s gained another conflicting value %r (%s) under %s" % (
                                field, conflict["value"], conflict["source_type"], existing_c["id"]),
                            contradiction_id=existing_c["id"], field=field)
        return {"classification": "contradiction", "contradiction_id": existing_c["id"],
                "fact_ids": [v["fact_id"] for v in existing_c["values"]],
                "cross_stream": any(v["stream"] != conflict["stream"] for v in existing_c["values"]),
                "field": field}

    conflict = _make_fact(record, raw)
    conflict["superseded"] = True            # not used downstream as active...
    conflict["needs_human_review"] = True
    record["facts"].append(conflict)

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
