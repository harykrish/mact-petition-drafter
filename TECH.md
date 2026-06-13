# Engineering notes

Built with the **Claude API** — model **`claude-opus-4-8`** (pinned in
[`src/config.py`](src/config.py); override via `MACT_MODEL`). This doc is for
reviewers: it records *how* the model is used and how "done" is machine-checked.
The product UI itself stays model-agnostic by design.

## How Opus 4.8 is used (beyond a basic call)

The loop uses the model in four distinct roles, each tuned to the task:

1. **Structured extraction** — `llm.extract_facts` pulls sourced facts from each
   document using **structured outputs** (`output_config.format` with a JSON
   schema), so every fact comes back typed and parseable. Provenance
   (stream, source_doc, source_type) is attached by the harness, never trusted
   from the model.

2. **Vision OCR on real scans** — `llm.extract_facts_from_path` sends PDFs and
   scan images (CT/MRI report photos, the FIR image, lab sheets) as **document /
   image content blocks**, using the model's high-resolution vision to read the
   text *and* understand the document in one pass. It also returns AI *visual
   observations* as a separate, low-confidence, review-flagged class so they
   never leak into the petition as settled fact. Large images are auto-downscaled.

3. **Two independent verifier agents, fresh context** — KB grading
   (`llm.kb_grade`) and petition grading (`llm.petition_grade`) run as *separate*
   `messages.create` calls whose context contains only the artifact + the rubric
   — no shared history with the drafter/extractor. They use **adaptive thinking**
   (`thinking: {type: "adaptive"}`) with **`output_config.effort`** so the model
   reasons about each rubric item before returning a structured verdict.

4. **The drafter** (`llm.draft_petition`) writes the petition from KB facts only,
   citing the fact ids each head rests on, at high effort.

Network-resilience details (non-streaming + bounded timeout + retries) live in
`llm._client` / the call sites — added after flaky-network failures during the
build.

## How "done" is machine-checkable (orchestration)

Another team can drop a different case's documents into `/data/` and rerun the
same loop against the same rubrics. Completion is verifiable without a human:

| Criterion | Enforced by |
|---|---|
| KB self-consistent across 3 streams | `src/reconcile.py` (stream ownership, authority-based new/correction/contradiction/duplicate) |
| ≥1 cross-stream contradiction caught, unprompted | `knowledge/changelog.md` (marked **CONTRADICTION**) |
| KB passes every invariant before commit | `src/verify_kb.py` grades `rubric/kb_invariants.md`; **commit only on pass** |
| Petition uses only KB facts, each head citing fact ids | `src/draft_petition.py` |
| Petition passes every MUST, arithmetic re-derived & matching | `src/verify_petition.py` grades `rubric/petition_rubric.md`; the Sarla Verma / Pranay Sethi math is **re-derived in plain Python**, independent of the drafter |

Offline, no API key required — proves the deterministic engine and the full
event wiring (including inject → catch → revise):

```bash
python -m scripts.selftest   # reconcile + invariants + precedent arithmetic
python -m scripts.itest      # full pipeline + SSE event stream
```

The KB verifier earned its keep during the build: it caught an I5 "silent
overwrite" bug in the contradiction-collapse code and refused to commit a
malformed KB — exactly as designed.

## Repeatability

- Synthetic demo run → committed `knowledge/case_record.json`, `changelog.md`,
  `petition_draft.md` (public "done" evidence) and `synthetic/replay_trace.json`
  (drives the instant Replay).
- Real run → `python -m scripts.run_real`, writing every artifact to the
  gitignored `data/_run/` so real PII is never committed or deployed.
