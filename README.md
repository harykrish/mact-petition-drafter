# Cambrian

A **living knowledge base for catastrophic injury** — powering legal drafting,
medical advocacy, rehab planning, and AAC communication from a single, self-maintaining
case record.

> Every 24 seconds, someone dies on the world's roads. Over 50 million more are
> injured each year. In India alone: 155,000+ annual deaths, over a million MACT
> cases stuck in tribunals, $10 billion in unpaid compensation, and 90% of claims
> stalled by documentation problems. Families face this while already dealing with
> the trauma of losing — or watching — a loved one suffer.

Cambrian ingests every document in a catastrophic injury case — police reports,
hospital records, disability certificates, salary slips, insurance papers — and
builds a **structured, sourced, self-consistent knowledge base**. From that one KB,
multiple agents act:

- **Legal drafting** — MACT petition with every rupee traced to a sourced fact
- **Medical advocacy** — treatment timeline, prognosis tracking, second-opinion prep
- **Rehab planning** — milestone tracking, therapy scheduling, equipment needs
- **AAC communication** — for patients who've lost the ability to speak

Today's demo shows **NyayaSetu**, the legal agent. The architecture generalizes to every spoke.

## Architecture

```
Documents (9+)
     │
     ▼
┌──────────┐    ┌─────────────┐    ┌──────────────┐    ┌───────────┐    ┌─────────────────┐
│  Ingest  │───▶│  Reconcile  │───▶│  Verify KB   │───▶│   Draft   │───▶│ Verify Petition │
│          │    │             │    │ (independent) │    │           │    │  (independent)  │
│ Extract  │    │ Catch cross-│    │ Fresh context │    │ KB facts  │    │ Re-derive every │
│ sourced  │    │ stream      │    │ 10 invariants │    │ only, cite│    │ number from     │
│ facts    │    │ conflicts   │    │ No shared     │    │ fact IDs  │    │ scratch — reject│
│ (struct) │    │             │    │ history       │    │           │    │ if wrong        │
└──────────┘    └─────────────┘    └──────────────┘    └───────────┘    └────────┬────────┘
                                                                                │
                                                                    ◄───────────┘
                                                              Autonomous revision loop:
                                                              rejects → structured feedback
                                                              → drafter revises (no human)
```

**12+ orchestrated Claude calls. 2 independent verification agents. Fresh-context
separation — verifiers never see the drafter's history.**

## The key insight: fresh-context verification

The verifiers are not "checking the drafter's work" with access to the drafter's
reasoning. They run as **separate model calls** whose context contains *only* the
artifact being verified plus the grading rubric. No shared conversation history,
no memory of extraction. This means:

- A hallucinated citation can't hide behind plausible reasoning the verifier inherits
- Arithmetic errors are caught deterministically (Python re-derivation, not LLM review)
- If any check fails, the verifier sends structured feedback and the drafter revises autonomously

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

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

## Run on your real case (private — never committed)

Drop real documents into `data/{police,medical,financial}/` (any mix of
`.pdf`, `.docx`, `.txt`, `.md`, `.json`, and images). PDFs and scan images are
read **directly by the model's vision** — it OCRs the text and understands the
document structure in one pass. Large images are auto-downscaled so none are skipped.

```bash
python -m scripts.run_real --list             # show what would be ingested (no API calls)
python -m scripts.run_real                    # ALL docs incl. scan images
python -m scripts.run_real --no-images        # text/pdf/docx only
python -m scripts.run_real --stream financial # one stream only
python -m scripts.run_real --max 20           # cap file count (cost control)
```

**Every artifact from a real run is written to `data/_run/`, which is gitignored** —
real PII is never committed.

## Tests (no API key required)

```bash
python -m scripts.selftest   # reconcile + invariants + precedent arithmetic (21 checks)
python -m scripts.itest      # full pipeline + SSE event stream (12 checks)
```

`selftest` asserts the cross-stream accident-date contradiction is caught, the
income correction supersedes the preliminary CA certificate (prior value kept in
history), and the loss of future earning re-derives to ₹9,36,00,000
(`7200000 × 1.25 × 13 × 80%` — a self-employed claimant per the Pranay Sethi table).

## Claude Code dynamic workflow

The repo includes a `/verify-release` Claude Code workflow (`.claude/workflows/verify-release.md`)
that fans out **5 parallel verification agents**:

| Agent | What it checks |
|-------|---------------|
| selftest | Deterministic engine: reconciliation, invariants, arithmetic |
| itest | Full pipeline + SSE event wiring, including inject → catch → revise |
| rubric-auditor | KB + petition against both rubric files, every MUST graded |
| deploy-checker | Live deployed endpoints: health, corpus, state, replay |
| adversarial-verifier | Independent hunt for untraceable facts or arithmetic errors |

A synthesis step merges all 5 into a PASS/FAIL release-readiness verdict.

## Deploy (Render or Railway)

A single Python web service — no database, no build step.

- **Render:** [`render.yaml`](render.yaml). Create a Web Service and set `ANTHROPIC_API_KEY`.
- **Railway:** [`railway.json`](railway.json) / [`Procfile`](Procfile). Add `ANTHROPIC_API_KEY` as a variable.

Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`.

## Layout

```
/data/        GITIGNORED — real case documents, never committed
/synthetic/   fake demo corpus (3 streams, 9 docs; fictional TBI/polytrauma case)
/precedent/   case-law notes: Sarla Verma, Pranay Sethi, Kavin
/rubric/      kb_invariants.md, petition_rubric.md — the grading targets
/knowledge/   case_record.json, changelog.md (generated; committed as "done" evidence)
/src/         pipeline modules        /static/  the web UI
/scripts/     selftest, itest, run    /logs/    verifier transcripts
/.claude/     workflows/ + agents/ — Claude Code dynamic orchestration
```

## Constraints

Facts only — never medical advice or clinical recommendations; the output is a
legal document. The repo is public; real documents live in `/data/` (gitignored)
and the demo runs entirely on the synthetic set.

---

Engineering & model details: [`TECH.md`](TECH.md).
