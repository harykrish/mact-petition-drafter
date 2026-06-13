# KB Invariants — `case_record.json`

> **Status: proposed v0**, derived from `brief.md`. Replace with the
> authoritative version if you have one — the loop grades against whatever
> lives in this file.

The KB verifier loads a *candidate* `case_record.json` in a **fresh context**
(no memory of ingest/reconcile) plus this file, and grades each invariant
`PASS` / `FAIL`. **Any `FAIL` on a MUST blocks the commit.** The transcript is
written to `/logs/kb_verify_<timestamp>.md`.

## Definitions
- **Active fact**: a fact with `superseded: false`.
- **Active set**: all active facts. This is the only set the drafter may read.

## MUST (a single FAIL blocks commit)

- **I1 — Complete provenance.** Every fact has non-empty `id`, `field`,
  `value`, `stream`, `source_doc`, `source_type`, `extracted_on`, and a
  numeric `confidence`.
- **I2 — Valid stream.** `stream ∈ {medical, police, financial}`.
- **I3 — Confidence range.** `0.0 ≤ confidence ≤ 1.0`.
- **I4 — Unique ids.** No two facts share an `id`.
- **I5 — No silent overwrite.** If a fact's `value` changed from a prior
  ingest, the prior value appears in that fact's `history[]` with its own
  `source_doc` and `extracted_on`. The superseded value is never deleted.
- **I6 — Contradictions parked, not resolved.** When two facts assert
  different `value`s for the same `field` from different sources and neither
  is a confidence-justified correction, the conflict appears in
  `contradictions[]` (referencing ≥2 sources) and is **not** silently
  collapsed into a single active fact.
- **I7 — Review flag is honest.** `needs_human_review` is `true` whenever
  `confidence < 0.80` **or** the fact participates in an unresolved
  contradiction (`status: "unresolved"`).
- **I8 — Append-only changelog.** `changelog[]` has strictly increasing
  `seq`, and **every** mutation to `facts[]` or `contradictions[]` has a
  corresponding changelog entry (`action`, `fact_id`/`contradiction_id`,
  `timestamp`, `summary`). No changelog entry is ever edited or removed.
- **I9 — Source within corpus.** Every `source_doc` path sits under one of
  `data/{medical,police,financial}/` or `synthetic/{medical,police,financial}/`,
  and its top-level stream directory matches the fact's `stream`.
- **I10 — Referential integrity.** Every `contradiction` and every
  `changelog` entry references `fact_id`s that exist in `facts[]`.

## SHOULD (FAIL is a warning, does not block)

- **S1 — One active fact per scalar field.** For single-valued fields
  (e.g. `victim_name`, `accident_date`), at most one active fact exists; the
  rest are superseded or parked as contradictions.
- **S2 — Resolution is recorded.** A `contradiction` moved to
  `status: "resolved"` has a non-null `resolution_note` explaining which
  source won and why.
- **S3 — Monotonic timestamps.** `extracted_on` values are non-decreasing
  along each fact's `history[]`.

## Output contract for the verifier
```json
{
  "result": "PASS" | "FAIL",
  "must": [{"id": "I1", "status": "PASS|FAIL", "note": "..."}, ...],
  "should": [{"id": "S1", "status": "PASS|FAIL", "note": "..."}, ...],
  "blocking_failures": ["I6", ...]
}
```
