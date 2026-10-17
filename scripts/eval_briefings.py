"""Measure the GenAI briefing on this machine: how often the verifier rejects the LLM's note,
and how long a note takes. Needs llama-cpp-python and RESCUENYC_LLM=/path/to/model.gguf
(big-endian GGUF on s390x).

    RESCUENYC_LLM=models/granite-be.gguf python scripts/eval_briefings.py --art artifacts --n 100
"""
import argparse
import json
import platform
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescueflow import briefing, model as m  # noqa: E402
from rescueflow.pipeline import load_table, payloads  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", type=Path, default=Path("artifacts"))
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()
    if not briefing.llm_available():
        raise SystemExit("set RESCUENYC_LLM to a GGUF model path")
    clf, meta = m.load(args.art)
    table = load_table(args.art / "borough_hour.csv").dropna(subset=["stress"])
    rows = table.sample(min(args.n, len(table)), random_state=0)
    results = []
    for p in payloads(clf, meta, rows):
        for b in p["boroughs"]:
            note, secs = briefing.llm_note(b)
            ok, bad = briefing.verify(note, {**b, "risk_percent": briefing.pct(b["p_stress"])})
            results.append({"note": note, "ok": ok, "unsupported": bad, "seconds": secs})
    out = {"machine": platform.machine(), "model": Path(briefing.os.environ["RESCUENYC_LLM"]).name,
           "notes": len(results), "rejection_rate": float(np.mean([not r["ok"] for r in results])),
           "median_s": float(np.median([r["seconds"] for r in results])),
           "examples_rejected": [r for r in results if not r["ok"]][:5]}
    (args.art / "briefing_eval.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "examples_rejected"}, indent=2))
