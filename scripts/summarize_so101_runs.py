"""Summarize per-episode results from a `runs/so101_phase4/` tree.

Walks every `episode_*/manifest.json`, pulls degrade reason, track-yield,
segment-coverage, and per-prompt sample counts, and prints a single table.
Pair with `logs/batch_so101/_gpu*_top.log` to see which episodes never
produced a run dir at all (typically fps.unresolvable from timestamp drift).

Run:
    uv run python scripts/summarize_so101_runs.py
    uv run python scripts/summarize_so101_runs.py --runs /custom/runs/root
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

EP_RE = re.compile(r"episode_(\d{6})")


def _ep_id(run_dir: Path) -> str:
    m = EP_RE.search(run_dir.name)
    return m.group(1) if m else run_dir.name


def _summarize_one(run_dir: Path) -> dict:
    out: dict = {"run": run_dir.name, "episode": _ep_id(run_dir)}
    try:
        m = json.loads((run_dir / "manifest.json").read_text())
    except Exception as exc:
        out["error"] = f"manifest read: {exc!r}"
        return out

    ps = m.get("pipeline_status", {}) or {}
    out["degrade"] = ps.get("degrade_reason")
    out["degraded_from"] = ps.get("degraded_from_phase")
    out["obj_state"] = ps.get("object_state_available")
    out["coverage"] = ps.get("object_state_segment_coverage")

    tracks_path = run_dir / "tracks.json"
    if tracks_path.is_file():
        try:
            t = json.loads(tracks_path.read_text())
            tlist = t.get("tracks", [])
            out["n_tracks"] = len(tlist)
            samples = [len(tr.get("samples", [])) for tr in tlist]
            out["max_samples"] = max(samples) if samples else 0
            out["sum_samples"] = sum(samples)
            out["prompts"] = ",".join(
                f"{tr.get('prompt')}({len(tr.get('samples', []))})"
                for tr in tlist
            )
        except Exception as exc:
            out["tracks_error"] = repr(exc)
    else:
        out["n_tracks"] = 0

    ann_path = run_dir / "annotation.json"
    if ann_path.is_file():
        try:
            a = json.loads(ann_path.read_text())
            out["n_segments"] = len(a.get("segments", []))
        except Exception:
            pass

    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--runs", default="runs/so101_phase4",
        help="root containing episode_*/ run directories",
    )
    p.add_argument(
        "--md",
        help=("optional output path for a Markdown summary "
              "(written only when this flag is given)"),
    )
    p.add_argument(
        "--logs", default="logs/batch_so101",
        help="batch log root; used to detect fps.unresolvable / never-ran episodes",
    )
    args = p.parse_args()

    root = Path(args.runs).resolve()
    if not root.is_dir():
        print(f"runs root not found: {root}")
        return 2

    rows = sorted(
        (_summarize_one(d) for d in root.iterdir()
         if d.is_dir() and d.name.startswith("episode")),
        key=lambda r: r.get("episode", ""),
    )

    if not rows:
        print(f"no episode runs in {root}")
        return 1

    # Header
    cols = (
        ("episode", 8),
        ("degrade", 32),
        ("obj_state", 9),
        ("cov", 5),
        ("segs", 5),
        ("tracks", 6),
        ("max_samples", 11),
        ("prompts", 0),
    )
    fmt = "  ".join(f"%-{w}s" if w else "%s" for _, w in cols)
    header_vals = tuple(name for name, _ in cols)
    print(fmt % header_vals)
    print(fmt % tuple("-" * (w if w else 5) for _, w in cols))

    n_ok = 0
    n_degrade = 0
    n_full_phase4 = 0
    coverage_sum = 0.0
    coverage_n = 0
    for r in rows:
        deg = r.get("degrade") or "-"
        cov = r.get("coverage")
        if cov is not None:
            coverage_sum += cov
            coverage_n += 1
        if r.get("degrade") is None:
            n_full_phase4 += 1
        else:
            n_degrade += 1
        n_ok += 1
        print(fmt % (
            r.get("episode", "?"),
            (deg if deg != "-" else "(none)")[:32],
            str(r.get("obj_state", "-")),
            f"{cov:.2f}" if cov is not None else "-",
            str(r.get("n_segments", "-")),
            str(r.get("n_tracks", "-")),
            str(r.get("max_samples", "-")),
            r.get("prompts", "-") or "-",
        ))

    print()
    print(f"runs found:           {n_ok}")
    print(f"  full phase 4:       {n_full_phase4}")
    print(f"  degraded:           {n_degrade}")
    if coverage_n:
        print(f"avg object coverage:  {coverage_sum / coverage_n:.2%}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
