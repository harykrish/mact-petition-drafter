"""Headless full run of the loop (needs ANTHROPIC_API_KEY).

    .venv/bin/python -m scripts.run                 # normal run
    .venv/bin/python -m scripts.run --inject-error  # demo the verifier catching an error
    .venv/bin/python -m scripts.run --git           # also git-commit the verified KB

Writes knowledge/case_record.json, knowledge/changelog.md, output/petition_draft.md
and verifier transcripts under logs/.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import llm, pipeline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inject-error", action="store_true", help="demo: inject an arithmetic error")
    ap.add_argument("--no-llm-verify", action="store_true", help="skip LLM verifier cross-checks (deterministic gate only)")
    ap.add_argument("--git", action="store_true", help="git-commit the KB on a passing verify")
    args = ap.parse_args()

    if not llm.api_key_present():
        print("ANTHROPIC_API_KEY is not set. Export it and retry.")
        return 2

    print("Running the loop on the synthetic corpus (model: see config)...\n")
    for kind, payload in pipeline.run_full_events(
            use_llm=not args.no_llm_verify, inject_error=args.inject_error, commit_git=args.git):
        if kind == "ingest":
            d = payload["doc"]
            kinds = {}
            for r in d["results"]:
                kinds[r["classification"]] = kinds.get(r["classification"], 0) + 1
            print("  ingest %-32s %2d facts  %s" % (d["source_doc"], d["extracted"], dict(kinds)))
        elif kind == "kb_verify":
            v = payload["verdict"]
            print("\nKB verify: %s  (committed=%s)" % (v["result"], payload["committed"]))
            for c in v["deterministic"]["must"]:
                if c["status"] != "PASS":
                    print("   FAIL %s — %s" % (c["id"], c["note"]))
        elif kind == "draft_attempt":
            a = payload
            print("\nDraft attempt %d: %s%s" % (
                a["attempt"], a["result"], " (error injected)" if a["injected_error"] else ""))
            rc = a["arithmetic"]["recomputed"]
            loss = rc.get("loss_of_future_earning")
            if loss:
                print("   re-derived loss of earning: %d  (%s)" % (loss["amount"], loss["formula"]))
            if a["blocking_failures"]:
                print("   blocking: %s" % a["blocking_failures"])
        elif kind == "draft_done":
            print("\nPetition: %s after %d revision(s)." % (
                "PASS" if payload["passed"] else "FAIL", payload["revisions"]))
        elif kind == "done":
            print("\nArtifacts written to knowledge/ and output/. Verifier logs in logs/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
