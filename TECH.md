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

## The fresh-context verification pattern

This is the strongest architectural decision in the system. It deserves its own
section because it's the difference between "LLM checks its own work" (unreliable)
and "independent agent audits an artifact" (reliable).

### Why it matters

When a drafter and verifier share conversation history, the verifier inherits the
drafter's reasoning chain. A hallucinated citation looks plausible because the
verifier "remembers" the reasoning that produced it. A miscalculated number passes
because the verifier saw the same (wrong) arithmetic steps.

### How Cambrian implements it

Each verifier runs as a **separate `messages.create` call** with a freshly
constructed context:

```
Verifier context = artifact (KB or petition) + rubric + nothing else
```

- **No extraction history** — the verifier doesn't know what documents were ingested
- **No drafter reasoning** — the verifier doesn't see how the petition was written
- **No prior verdicts** — each verification is independent of previous attempts

This means:
- A fact the drafter "remembers" from extraction but didn't actually source? The
  verifier can't find it in the KB → **FAIL**
- Arithmetic the drafter computed with extended thinking? The petition verifier
  **re-derives every number in plain Python** from the KB's raw figures → catches
  floating-point and formula errors deterministically
- A rubric item the drafter thought it satisfied? The verifier grades against the
  rubric text alone, with no inherited confidence

### The revision loop

When verification fails, the verifier returns **structured feedback** (which
specific items failed and why). The drafter receives this feedback and revises —
but crucially, the *next* verification is again a fresh context. The verifier
never learns to "expect" the drafter's style or trust its corrections.

This loop runs autonomously until the petition passes all MUSTs, or a maximum
attempt count is reached (currently 3). In practice, the most common failure is
an arithmetic rounding error that the Python re-derivation catches on the first
verification attempt.

### Real-world validation

This pattern has been tested on a real catastrophic injury case (not just the
synthetic demo corpus). Real hospital discharge summaries, FIR scans, disability
certificates, and salary documentation were processed through the same pipeline.
The verifier caught a date discrepancy between the FIR and hospital admission
record that a human paralegal had missed.

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
python -m scripts.selftest   # reconcile + invariants + precedent arithmetic (21 checks)
python -m scripts.itest      # full pipeline + SSE event stream (12 checks)
```

The KB verifier earned its keep during the build: it caught an I5 "silent
overwrite" bug in the contradiction-collapse code and refused to commit a
malformed KB — exactly as designed.

## Claude Code dynamic workflow

The repo includes Claude Code workflow and agent definitions:

- **`.claude/workflows/verify-release.md`** — Fans out 5 parallel verification
  agents (selftest, itest, rubric-auditor, deploy-checker, adversarial-verifier)
  and synthesizes a release-readiness verdict
- **`.claude/agents/adversarial-verifier.md`** — Independent petition checker
  that hunts for untraceable facts and arithmetic errors
- **`.claude/agents/rubric-auditor.md`** — Rubric compliance grader for KB
  invariants and petition rubric items

These demonstrate Claude Code orchestration: the workflow coordinates multiple
independent agents, each with a focused task and clear pass/fail criteria,
mirroring the fresh-context verification pattern used in the pipeline itself.

## Repeatability

- Synthetic demo run → committed `knowledge/case_record.json`, `changelog.md`,
  `petition_draft.md` (public "done" evidence) and `synthetic/replay_trace.json`
  (drives the instant Replay).
- Real run → `python -m scripts.run_real`, writing every artifact to the
  gitignored `data/_run/` so real PII is never committed or deployed.
