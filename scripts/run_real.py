"""Run the loop on the user's REAL documents in /data/ (needs ANTHROPIC_API_KEY).

    .venv/bin/python -m scripts.run_real            # documents only (pdf/docx/txt/json)
    .venv/bin/python -m scripts.run_real --include-images   # also send scan images to Opus
    .venv/bin/python -m scripts.run_real --list     # just list what would be ingested

ALL output (case_record.json, changelog.md, petition, verifier logs) is written
to data/_run/ — which is gitignored — so real PII is NEVER committed. The public
knowledge/ directory is only ever written by the synthetic demo.

This prints field names and classification counts, not extracted values, to keep
PII off the terminal.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, llm, pipeline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-images", action="store_true", help="also send scan images (jpg/png) to Opus vision")
    ap.add_argument("--list", action="store_true", help="list ingestible files and exit (no API calls)")
    ap.add_argument("--no-llm-verify", action="store_true", help="deterministic KB gate only")
    args = ap.parse_args()

    files = pipeline.real_corpus_files(include_images=args.include_images)
    if not files:
        print("No ingestible files found under data/{police,medical,financial}/.")
        return 1

    if args.list:
        print("Would ingest %d files (output → %s, gitignored):\n" % (len(files), config.REAL_PATHS.case_record.parent))
        for f in files:
            print("  %-9s %-32s  %s" % (f["stream"], f["source_type"], Path(f["rel"]).name))
        if not args.include_images:
            print("\n(images skipped; pass --include-images to include scans)")
        return 0

    if not llm.api_key_present():
        print("ANTHROPIC_API_KEY is not set. Put it in .env or export it, then retry.")
        return 2

    print("Running the loop on %d REAL documents. Output → %s (gitignored).\n"
          % (len(files), config.REAL_PATHS.case_record.parent))
    for kind, payload in pipeline.run_real_events(include_images=args.include_images,
                                                  use_llm=not args.no_llm_verify):
        if kind == "ingest":
            d = payload["doc"]
            if d.get("error"):
                print("  [skip] %-40s  (%s)" % (Path(d["source_doc"]).name, d["error"][:60]))
            else:
                kinds = Counter(r["classification"] for r in d["results"])
                print("  %-40s %2d facts  %s" % (Path(d["source_doc"]).name, d["extracted"], dict(kinds)))
        elif kind == "kb_verify":
            v = payload["verdict"]
            rec = payload["record"]
            n_contra = len(rec.get("contradictions", []))
            print("\nKB verify: %s  (committed=%s)  | facts=%d, contradictions=%d"
                  % (v["result"], payload["committed"],
                     len([f for f in rec["facts"] if not f.get("superseded")]), n_contra))
            for c in v["deterministic"]["must"]:
                if c["status"] != "PASS":
                    print("   FAIL %s — %s" % (c["id"], c["note"]))
        elif kind == "draft_attempt":
            a = payload
            print("\nDraft attempt %d: %s" % (a["attempt"], a["result"]))
            if a["blocking_failures"]:
                print("   blocking: %s" % a["blocking_failures"])
        elif kind == "draft_done":
            print("\nPetition: %s after %d revision(s)." % ("PASS" if payload["passed"] else "FAIL", payload["revisions"]))
        elif kind == "done":
            print("\nDone. Private artifacts in: %s" % payload["output_dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
