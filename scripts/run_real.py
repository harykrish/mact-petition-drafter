"""Run the loop on the user's REAL documents in /data/ (needs ANTHROPIC_API_KEY).

    .venv/bin/python -m scripts.run_real                 # ALL docs incl. scan images (vision OCR)
    .venv/bin/python -m scripts.run_real --no-images     # skip images (text/pdf/docx only)
    .venv/bin/python -m scripts.run_real --stream financial   # one stream only
    .venv/bin/python -m scripts.run_real --max 20        # cap how many files (cost control)
    .venv/bin/python -m scripts.run_real --list          # show what would be ingested (no API calls)

Images (scans, report photos, FIR images, lab results) are READ VIA VISION OCR
— the text is read and the document understood in one pass. Large images are
auto-downscaled so none are skipped.

ALL output (case_record.json, changelog.md, petition, verifier logs) is written
to data/_run/ — which is gitignored — so real PII is NEVER committed. The public
knowledge/ directory is only ever written by the synthetic demo. The CLI prints
field names and classification counts, not extracted values, to keep PII off the
terminal.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, llm, pipeline, supastore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-images", action="store_true", help="skip scan images; ingest text/pdf/docx only")
    ap.add_argument("--no-findings", action="store_true",
                    help="OCR/metadata only; skip AI visual observations of scans")
    ap.add_argument("--stream", action="append", choices=list(config.VALID_STREAMS),
                    help="limit to one or more streams (repeatable)")
    ap.add_argument("--max", type=int, default=None, help="cap the number of files (cost control)")
    ap.add_argument("--list", action="store_true", help="list ingestible files and exit (no API calls)")
    ap.add_argument("--no-llm-verify", action="store_true", help="deterministic KB gate only")
    ap.add_argument("--supabase", action="store_true",
                    help="after the run, push the KB to the shared Supabase (Cambrian) store")
    ap.add_argument("--case-id", default=None, help="case_id to use when pushing to Supabase")
    ap.add_argument("--title", default=None, help="human title for the case (e.g. 'R. Narayanan Santhanam')")
    args = ap.parse_args()

    include_images = not args.no_images
    files = pipeline.real_corpus_files(include_images=include_images, streams=args.stream, limit=args.max)
    if not files:
        print("No ingestible files found under data/{police,medical,financial}/.")
        return 1

    if args.list:
        print("Would ingest %d files (output → %s, gitignored):\n" % (len(files), config.REAL_PATHS.case_record.parent))
        for f in files:
            print("  %-9s %-32s  %s" % (f["stream"], f["source_type"], Path(f["rel"]).name))
        if args.no_images:
            print("\n(images skipped via --no-images)")
        return 0

    if not llm.api_key_present():
        print("ANTHROPIC_API_KEY is not set. Put it in .env or export it, then retry.")
        return 2

    print("Running the loop on %d REAL documents (images via vision OCR). Output → %s (gitignored).\n"
          % (len(files), config.REAL_PATHS.case_record.parent))
    for kind, payload in pipeline.run_real_events(include_images=include_images, streams=args.stream,
                                                  limit=args.max, use_llm=not args.no_llm_verify,
                                                  extract_observations=not args.no_findings):
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

    if args.supabase:
        import json
        rec = json.loads(Path(config.REAL_PATHS.case_record).read_text())
        if args.case_id:
            rec["case_id"] = args.case_id
        print("\nPushing KB to Supabase (case_id=%s) …" % rec.get("case_id"))
        counts = supastore.push_record(rec, title=args.title)
        print("  pushed: %s" % counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
