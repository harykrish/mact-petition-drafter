# Petition Rubric — MACT Compensation Petition

> **Status: proposed v0**, derived from `brief.md` and the precedent notes in
> `/precedent/`. Replace with the authoritative version if you have one.

The petition verifier runs in a **fresh context**. It loads the petition
draft, `knowledge/case_record.json`, this rubric, and `/precedent/`. It
**re-computes every number from scratch** from the cited KB facts and grades
each item `PASS` / `FAIL` / `PARTIAL`. Any `FAIL` on a MUST returns `revise`
with the failures fed back to the drafter. Transcript →
`/logs/petition_verify_<timestamp>.md`.

## MUST (a single FAIL → `revise`)

- **M1 — Every head is sourced.** Each numbered compensation head cites the
  KB `fact_id`(s) it rests on.
- **M2 — No untraceable fact.** No factual assertion (name, date, age,
  income, disability %, expense) appears in the petition without a citable KB
  fact id. The verifier spot-checks each against the active set.
- **M3 — Income from financial stream.** The income figure used originates
  from a `stream: "financial"` fact.
- **M4 — Disability from medical stream.** The functional disability % used
  originates from a `stream: "medical"` disability-assessment fact.
- **M5 — Liability from police stream.** Negligence / fault is pleaded from
  `stream: "police"` facts (FIR / charge sheet).
- **M6 — Multiplier correct.** The multiplier matches the victim's age band
  per the Sarla Verma table (see `/precedent/sarla_verma.md`).
- **M7 — Future prospects correct.** The future-prospects addition matches
  the victim's age band and employment type per Pranay Sethi
  (see `/precedent/pranay_sethi.md`).
- **M8 — Loss-of-earning arithmetic.** For an injury claim, loss of future
  earning capacity is re-computed as:
  `annual_income × (1 + future_prospects) × multiplier × functional_disability%`
  and matches the petition **to the rupee**.
- **M9 — Medical expenses arithmetic.** The medical-expenses head equals the
  sum of the itemized bill facts it cites.
- **M10 — Total arithmetic.** The grand total equals the sum of all heads,
  re-computed independently, matching to the rupee.
- **M11 — Precedent grounded.** The petition cites Sarla Verma (2009) and
  Pranay Sethi (2017) where it applies their formulae, plus the recent
  authority noted in `/precedent/kavin.md`.
- **M12 — Disputed facts not asserted as settled.** No fact with
  `needs_human_review: true` or any value still `unresolved` in
  `contradictions[]` is stated as established. It is either omitted or
  explicitly flagged as disputed in the petition.
- **M13 — Facts only, no clinical advice.** The petition contains no medical
  advice or clinical recommendation — only documented facts presented as a
  legal claim.

## SHOULD (FAIL is a warning)

- **S1 — Conventional heads.** Includes the applicable conventional heads
  (pain & suffering, loss of amenities, attendant/nursing, future medical,
  special diet/conveyance) per Pranay Sethi where facts support them.
- **S2 — Interest.** Pleads interest on the awarded sum from date of petition.
- **S3 — Jurisdiction & parties.** Names the Tribunal, the claimant(s), the
  respondents (driver / owner / insurer), and pleads jurisdiction.
- **S4 — Structure.** Standard petition structure: cause title, parties,
  facts of accident, injuries, income, heads of compensation, prayer.

## Output contract for the verifier
```json
{
  "result": "pass" | "revise",
  "must": [{"id": "M1", "status": "PASS|FAIL|PARTIAL", "note": "..."}, ...],
  "should": [{"id": "S1", "status": "PASS|FAIL|PARTIAL", "note": "..."}, ...],
  "recomputed": {
    "loss_of_earning": <int>,
    "medical_expenses": <int>,
    "grand_total": <int>
  },
  "blocking_failures": ["M8", ...],
  "feedback_to_drafter": "..."
}
```
