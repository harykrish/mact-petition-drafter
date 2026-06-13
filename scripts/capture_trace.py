"""Capture one full pipeline run to synthetic/replay_trace.json for the web app's
Replay mode — an instant, no-API animation of the whole loop.

Runs against a scratch output dir so it never overwrites the committed knowledge/.
Needs ANTHROPIC_API_KEY. Run: .venv/bin/python -m scripts.capture_trace
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, llm, pipeline  # noqa: E402


def main() -> int:
    if not llm.api_key_present():
        print("ANTHROPIC_API_KEY not set."); return 2
    tmp = Path(tempfile.mkdtemp(prefix="mact_capture_"))
    paths = config.CasePaths(tmp / "cr.json", tmp / "cl.md", tmp / "pet.md", tmp / "logs")

    ingest, kb_verify, draft, record = [], None, None, None
    for kind, payload in pipeline.run_full_events(use_llm=True, paths=paths):
        if kind == "ingest":
            ingest.append(payload["doc"])
            print("  ingest", payload["doc"]["source_doc"], payload["doc"]["extracted"], "facts")
        elif kind == "kb_verify":
            kb_verify = {"result": payload["verdict"]["result"],
                         "committed": payload["committed"],
                         "must": payload["verdict"]["deterministic"]["must"],
                         "should": payload["verdict"]["deterministic"]["should"],
                         "llm_result": (payload["verdict"].get("llm") or {}).get("result")}
            print("  kb_verify", kb_verify["result"], "committed", kb_verify["committed"])
        elif kind == "draft_done":
            draft = payload
            print("  draft passed", payload["passed"], "revisions", payload["revisions"])
        elif kind == "done":
            record = payload["record"]

    trace = {
        "case_id": record["case_id"],
        "captured_at": pipeline.store.now_iso(),
        "ingest": ingest,
        "kb_verify": kb_verify,
        "draft": draft,
        "record": record,
    }
    out = config.SYNTHETIC_DIR / "replay_trace.json"
    out.write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")
    n_contra = len(record["contradictions"])
    print("\nWrote %s  (facts=%d, contradictions=%d, petition_passed=%s)" % (
        out, len([f for f in record["facts"] if not f.get("superseded")]), n_contra,
        draft["passed"] if draft else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
