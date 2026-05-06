"""Aggregate Gemma I/O dumps into JSONL files (FT-friendly).

Walks the dump root produced by ``MIMICANNO_VLM_DUMP_DIR`` and emits two
JSONL files:

* ``planner.jsonl`` — one row per object-extraction call.
* ``labeler.jsonl`` — one row per per-segment label attempt.

Image paths are written as POSIX relative paths anchored at the dump
root, so the bundle (``planner.jsonl + labeler.jsonl + episode_*/``)
stays portable.

Run:
    uv run python scripts/aggregate_gemma_pairs.py
    uv run python scripts/aggregate_gemma_pairs.py \
        --dumps runs/so101_phase4_v2/_vlm_dumps \
        --out   runs/so101_phase4_v2/_vlm_dumps/aggregated
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _try_json(text: str) -> tuple[Any, bool]:
    try:
        return json.loads(text), True
    except Exception:
        return None, False


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def collect_planner(dumps_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ep_dir in sorted(dumps_root.glob("episode_*")):
        planner_root = ep_dir / "_planner"
        if not planner_root.is_dir():
            continue
        for call_dir in sorted(planner_root.glob("call_*")):
            prompt_p = call_dir / "prompt.txt"
            response_p = call_dir / "response.txt"
            frame_p = call_dir / "frame.png"
            if not (prompt_p.is_file() and response_p.is_file()):
                continue
            response_text = _read_text(response_p)
            response_json, parsed = _try_json(response_text)
            rows.append({
                "episode": ep_dir.name,
                "call_id": call_dir.name,
                "prompt": _read_text(prompt_p),
                "response_text": response_text,
                "response_json": response_json,
                "response_parsed_ok": parsed,
                "image": _rel(frame_p, dumps_root) if frame_p.is_file() else None,
            })
    return rows


def collect_labeler(dumps_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ep_dir in sorted(dumps_root.glob("episode_*")):
        for seg_dir in sorted(p for p in ep_dir.iterdir()
                              if p.is_dir() and p.name != "_planner"):
            for attempt_dir in sorted(seg_dir.glob("attempt_*")):
                prompt_p = attempt_dir / "prompt.txt"
                response_p = attempt_dir / "response.txt"
                request_p = attempt_dir / "request.json"
                if not (prompt_p.is_file() and response_p.is_file()):
                    continue
                response_text = _read_text(response_p)
                response_json, parsed = _try_json(response_text)
                meta: Any = None
                if request_p.is_file():
                    meta, _ = _try_json(_read_text(request_p))
                keyframes = [
                    _rel(p, dumps_root)
                    for p in sorted(attempt_dir.glob("keyframe_*.png"))
                ]
                attempt_num = int(attempt_dir.name.split("_")[-1])
                rows.append({
                    "episode": ep_dir.name,
                    "segment_id": seg_dir.name,
                    "attempt": attempt_num,
                    "prompt": _read_text(prompt_p),
                    "response_text": response_text,
                    "response_json": response_json,
                    "response_parsed_ok": parsed,
                    "keyframes": keyframes,
                    "meta": meta,
                })
    return rows


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False))
            f.write("\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dumps", default="runs/so101_phase4_v2/_vlm_dumps",
                   help="Dump root (the dir passed as MIMICANNO_VLM_DUMP_DIR's parent).")
    p.add_argument("--out", default=None,
                   help="Output dir (default: <dumps>/aggregated).")
    args = p.parse_args()

    dumps_root = Path(args.dumps).resolve()
    if not dumps_root.is_dir():
        print(f"dumps root not found: {dumps_root}")
        return 2
    out_dir = Path(args.out).resolve() if args.out else dumps_root / "aggregated"

    planner_rows = collect_planner(dumps_root)
    labeler_rows = collect_labeler(dumps_root)

    write_jsonl(planner_rows, out_dir / "planner.jsonl")
    write_jsonl(labeler_rows, out_dir / "labeler.jsonl")

    planner_ok = sum(1 for r in planner_rows if r["response_parsed_ok"])
    labeler_ok = sum(1 for r in labeler_rows if r["response_parsed_ok"])
    eps_p = sorted({r["episode"] for r in planner_rows})
    eps_l = sorted({r["episode"] for r in labeler_rows})

    print(f"dumps_root: {dumps_root}")
    print(f"out_dir:    {out_dir}")
    print(f"planner.jsonl: {len(planner_rows)} rows  "
          f"(parse-ok={planner_ok}, episodes={len(eps_p)})")
    print(f"labeler.jsonl: {len(labeler_rows)} rows  "
          f"(parse-ok={labeler_ok}, episodes={len(eps_l)})")
    if len(eps_p) != len(eps_l):
        only_p = set(eps_p) - set(eps_l)
        only_l = set(eps_l) - set(eps_p)
        if only_p:
            print(f"  episodes with planner only: {sorted(only_p)}")
        if only_l:
            print(f"  episodes with labeler only: {sorted(only_l)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
