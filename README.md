# MACT Petition Drafter

A self-maintaining case knowledge base that drafts a precedent-grounded
compensation petition for Indian **Motor Accident Claims Tribunal (MACT)** cases —
and verifies its own work.

> Ingest documents → reconcile facts into a self-consistent KB → verify the KB
> against a rubric in a **fresh context** → draft a petition from the KB alone →
> an **independent verifier re-derives every number** and sends the draft back if
> it doesn't add up. All on `claude-opus-4-8`.

See [`brief.md`](brief.md) for the problem statement, who it's for, and the bar for "done".

## Why this is hard (and what the loop automates)

A MACT petition takes a paralegal weeks. The work isn't the writing — it's
reconciling three unrelated document streams into one coherent factual picture,
then turning that into a petition where every rupee traces to a document.

| Stream | Establishes | Example documents |
|--------|-------------|-------------------|
| **police** | liability (who is at fault) | FIR, charge sheet |
| **medical** | disability quantum | discharge summary, disability certificate, hospital bill |
| **financial** | income loss | salary slip, Form 16 / ITR |

These disagree. The loop **catches cross-stream contradictions on its own** and
parks them for a human instead of silently picking a winner.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # Build Day $500 credits

# Web app (the demo):
uvicorn app:app --reload --port 8000        # open http://localhost:8000

# Or headless:
python -m scripts.run                       # full run on the synthetic corpus
python -m scripts.run --inject-error        # watch the verifier catch & fix an arithmetic error
```

The web UI streams the run live: documents ingesting into three streams, facts
classified as new / correction / **contradiction** / duplicate, the knowledge
base building up, the contradictions panel lighting up when a conflict is caught,
the changelog timeline, the drafted petition, and the verifier's **independent
arithmetic re-derivation shown beside the drafter's numbers**.

## Tests (no API key required)

The deterministic engine and the full pipeline/SSE wiring are tested offline by
stubbing the model calls:

```bash
python -m scripts.selftest   # reconcile + invariants + precedent arithmetic
python -m scripts.itest      # full pipeline + event stream, incl. inject→catch→revise
```

`selftest` asserts the cross-stream accident-date contradiction is caught, the
income correction supersedes the preliminary CA certificate (prior value kept in
history), and the loss of future earning re-derives to ₹9,36,00,000
(`7200000 × 1.25 × 13 × 80%` — a self-employed claimant per the Pranay Sethi table).

## Deploy (Render or Railway)

A single Python web service — no database, no build step.

- **Render:** the repo includes [`render.yaml`](render.yaml). Create a Web Service
  from the repo and set `ANTHROPIC_API_KEY` in the dashboard.
- **Railway:** [`railway.json`](railway.json) / [`Procfile`](Procfile) set the start
  command. Add `ANTHROPIC_API_KEY` as a variable.

Start command (both): `uvicorn app:app --host 0.0.0.0 --port $PORT`.

## How "done" is machine-checkable (orchestration)

| Criterion | Where it's enforced |
|-----------|---------------------|
| KB self-maintains across all 3 streams | `src/reconcile.py` + the synthetic corpus |
| ≥1 cross-stream contradiction caught, unprompted | logged in `knowledge/changelog.md` (marked **CONTRADICTION**) |
| KB passes every invariant before commit | `src/verify_kb.py` grades `rubric/kb_invariants.md`; commit only on pass |
| Petition uses **only** KB facts, each head citing fact ids | `src/draft_petition.py` (drafter reads the KB, never raw docs) |
| Petition passes every MUST, arithmetic re-derived & matching | `src/verify_petition.py` grades `rubric/petition_rubric.md` |

Drop a different case's documents into `/data/` and rerun the same loop against
the same rubrics — nothing is hard-coded to this case.

## Architecture

```
synthetic/ or data/   →  src/ingest.py     extract structured, sourced facts (Opus, JSON schema)
                         src/reconcile.py  classify new/correction/contradiction/duplicate
knowledge/case_record.json  ← single source of truth (facts[] + contradictions[] + changelog[])
                         src/verify_kb.py  invariant gate + fresh-context Opus cross-check → commit on pass
                         src/draft_petition.py  petition from KB facts only (Opus)
                         src/verify_petition.py independent arithmetic (Python) + fresh-context Opus grading
output/petition_draft.md     ← the deliverable      logs/  ← every verifier transcript
```

The verifiers run as **separate model calls with only the artifact + rubric in
context** — no shared history with the drafter. The petition verifier re-derives
the Sarla Verma / Pranay Sethi math in plain Python, so an arithmetic error in the
draft is caught deterministically and fed back for revision.

## Layout

```
/data/        GITIGNORED — real case documents, never committed
/synthetic/   fake demo corpus (3 streams, 9 docs; fictional TBI/polytrauma case) + manifest.json
/precedent/   case-law notes: Sarla Verma, Pranay Sethi, Kavin (citation flagged)
/rubric/      kb_invariants.md, petition_rubric.md — the grading targets
/knowledge/   case_record.json, changelog.md (generated; committed as "done" evidence)
/src/         pipeline modules        /static/  the web UI        /logs/  verifier transcripts
/scripts/     selftest, itest, run
```

## Constraints

Facts only — never medical advice or clinical recommendations; the output is a
legal document. The repo is public; real documents live in `/data/` (gitignored)
and the demo runs entirely on the synthetic set. Model: `claude-opus-4-8`.
