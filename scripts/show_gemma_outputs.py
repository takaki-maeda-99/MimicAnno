"""Print every Gemma output (planner + labeler) found in runs/so101_phase4/.

For each episode shows:
- tracking_plan (planner step) — entities Gemma extracted
- annotation segments (labeler step) — per-segment verb/object/target/evidence

Run:
  uv run python scripts/show_gemma_outputs.py
  uv run python scripts/show_gemma_outputs.py --runs runs/so101_phase4
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", default="runs/so101_phase4")
    args = p.parse_args()

    root = Path(args.runs).resolve()
    if not root.is_dir():
        print(f"runs root not found: {root}")
        return 2

    runs = sorted(d for d in root.iterdir()
                  if d.is_dir() and d.name.startswith("episode"))
    if not runs:
        print(f"no runs in {root}")
        return 1

    for run in runs:
        ep = run.name.split("__")[0].replace("episode_", "")
        print(f"=== ep{ep} ({run.name}) ===")

        # Planner output (tracking_plan)
        tracks = run / "tracks.json"
        if tracks.is_file():
            try:
                t = json.loads(tracks.read_text())
                plan = t.get("tracking_plan", {}) or {}
                print(f"  planner:  task='{plan.get('task_text', '')}'")
                print(f"            objects={plan.get('object_prompts')}  "
                      f"targets={plan.get('target_prompts')}  "
                      f"tools={plan.get('tool_prompts')}")
                failed = plan.get("failed_prompts") or []
                if failed:
                    fmt = ", ".join(f"{f.get('prompt')}({f.get('role')})" for f in failed)
                    print(f"            failed_prompts: {fmt}")
            except Exception as exc:
                print(f"  planner:  ERROR {exc!r}")
        else:
            print(f"  planner:  (no tracks.json — degraded?)")

        # Labeler output (annotation segments)
        ann = run / "annotation.json"
        if ann.is_file():
            try:
                a = json.loads(ann.read_text())
                segs = a.get("segments", []) or []
                if not segs:
                    print(f"  labeler:  (no segments)")
                for seg in segs:
                    rng = f"[{seg.get('start_frame')}-{seg.get('end_frame')}]"
                    verb = seg.get("verb")
                    obj = seg.get("object")
                    tgt = seg.get("target")
                    conf = seg.get("phase_confidence") or seg.get("vlm_confidence")
                    ev = (seg.get("evidence") or "").replace("\n", " ")
                    print(f"  labeler:  {rng} verb={verb} obj={obj} tgt={tgt} "
                          f"conf={conf}")
                    if ev:
                        print(f"            evidence: {ev[:120]}")
            except Exception as exc:
                print(f"  labeler:  ERROR {exc!r}")
        else:
            print(f"  labeler:  (no annotation.json)")

        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
