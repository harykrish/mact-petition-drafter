# Brief: Self-Maintaining Case Knowledge Base → MACT Petition Drafter

## The problem
Filing a Motor Accident Claims Tribunal (MACT) compensation petition takes a
paralegal or junior advocate weeks. The work is not the writing — it is
reconciling evidence from three unrelated document streams into one coherent,
internally consistent factual picture, then translating that into a
precedent-grounded petition where every compensation head is justified and
every number traces to a document.

- **Police documents** establish *liability* (who is at fault): FIR, charge sheet.
- **Medical documents** establish *disability quantum* (severity, permanence,
  future care): discharge summaries, disability assessment certificates.
- **Financial documents** establish *income loss* (earning capacity, dependency):
  income proof, tax returns, salary records.

These arrive at different times, in different formats, and frequently disagree
with each other (a date in the FIR that doesn't match the hospital admission
note; an income figure that conflicts across documents). Today a human catches
those conflicts by hand, slowly, and often misses them.

## Who it is for
The **claimant's advocate** (lawyer / paralegal) preparing the petition. They
are the user who briefs the system with the case documents and receives a
drafted petition plus a clear record of what was reconciled and what conflicts
were found. Secondary beneficiary: the claimant, who gets a faster, more
complete, better-substantiated claim.

## What we are building
A knowledge base that **maintains its own integrity** as documents arrive, and
a petition drafter that consumes it.

1. **Ingest** — extract structured, sourced facts from each document.
2. **Reconcile** — classify each new fact against the existing record as
   new / correction / contradiction / duplicate. Corrections preserve prior
   values in history. Contradictions are flagged, never silently overwritten.
3. **Verify (KB)** — an independent verifier agent grades every proposed update
   against `/rubric/kb_invariants.md` in a fresh context. Commit only on pass.
4. **Draft** — generate the MACT petition using only facts in the knowledge
   base, every head citing the fact IDs it rests on.
5. **Verify (petition)** — a fresh verifier agent grades the draft against
   `/rubric/petition_rubric.md`, re-computes all arithmetic independently, and
   returns pass / revise. Revisions feed failures back to the drafter.

## What "done" looks like (the bar for today)
A precedent-grounded MACT petition draft that:
- is generated **entirely from the knowledge base** (no fact in the petition
  that doesn't trace to a KB fact, which traces to a document);
- was produced after the KB **self-maintained across all three document
  streams** (medical, police, financial);
- where the loop **flagged at least one cross-stream contradiction on its own**,
  logged in `changelog.md`, without a human pointing it out;
- and which **passes every MUST in `petition_rubric.md`** as graded by the
  independent verifier, with the arithmetic re-computed from scratch and
  matching.

"Done" is machine-checkable: a committed `case_record.json`, a `changelog.md`
showing the caught contradiction, and a verifier returning `pass` on the
petition. No human judgment required to confirm completion.

## Constraints
- Facts only — the system stores and reasons over **documented facts**, never
  medical advice or clinical recommendations. The output is a legal document.
- The repo is public at submission. Real case documents live in `/data/`
  (gitignored) and are never committed. The demo runs on the synthetic set.
- Model: `claude-opus-4-8`.

## How completion is verified by the model (orchestration)
- `kb_invariants.md` — graded on every KB update.
- `petition_rubric.md` — graded on the petition, arithmetic re-derived.
- `changelog.md` — append-only evidence of what changed and what conflicted.
Another team could drop a different case's documents into `/data/` and rerun
the same loop against the same rubrics tomorrow.
