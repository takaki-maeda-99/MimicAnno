#!/usr/bin/env python3
"""Diagnose MediaPipe handedness flip rate across adjacent frames.

Reads per-frame pkls from a ``scripts/run_hand_estimation.py`` output
directory and counts how often the same physical hand (matched by bbox
centre proximity) gets a different ``is_right`` label across consecutive
frames.

The motivation is that MediaPipe's Tasks API processes each frame
independently in IMAGE mode; the model's left/right classifier is per-
frame, so transient flips ("right hand" one frame, "left hand" the next
without the operator's hand actually crossing the midline) are common
when both hands are visible and similar in appearance. Switching to
VIDEO mode or adding a spatial-order tiebreaker mitigates this; this
script quantifies the problem on a real run so the cost/benefit of the
fix is visible.

Usage:

    scripts/diagnose_handedness_flip.py runs/gx010085_full
    scripts/diagnose_handedness_flip.py runs/X --distance-threshold 75

Output (machine-readable summary at the end so the PR description can
copy-paste the figures):

    Total adjacent-frame hand pairs: N
    Flips:                            K
    Flip rate:                        X.X%

Exclusions (the spatial correspondence is not well-defined):

- Frames where the count of detected hands differs from the previous
  frame (1-hand <-> 2-hand transition).
- Bbox-centre distance >= ``--distance-threshold`` pixels (a different
  physical hand, not a continuation).

Pairing rule for 2-hand frames: greedy nearest-neighbour by bbox centre.
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


def _bbox_centre(bbox: Sequence[float]) -> Tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return (float(x0 + x1) / 2.0, float(y0 + y1) / 2.0)


def _load_hands(pkl_path: Path) -> Optional[list]:
    try:
        with pkl_path.open("rb") as fp:
            data = pickle.load(fp)
    except Exception as exc:
        print(f"  warning: failed to load {pkl_path.name}: {exc!r}", file=sys.stderr)
        return None
    return list(data) if data is not None else []


def _greedy_match(
    prev: Sequence,
    curr: Sequence,
    *,
    max_dist: float,
) -> List[Tuple[int, int, float]]:
    """Greedy nearest-neighbour pairing between two hand sets.

    Returns ``(prev_idx, curr_idx, distance)`` tuples. Pairs whose distance
    exceeds ``max_dist`` are dropped.
    """
    prev_centres = [_bbox_centre(h.bbox) for h in prev]
    curr_centres = [_bbox_centre(h.bbox) for h in curr]
    candidates: List[Tuple[float, int, int]] = []
    for i, (px, py) in enumerate(prev_centres):
        for j, (cx, cy) in enumerate(curr_centres):
            d = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
            if d < max_dist:
                candidates.append((d, i, j))
    candidates.sort()
    used_prev: set[int] = set()
    used_curr: set[int] = set()
    matches: List[Tuple[int, int, float]] = []
    for d, i, j in candidates:
        if i in used_prev or j in used_curr:
            continue
        used_prev.add(i)
        used_curr.add(j)
        matches.append((i, j, d))
    return matches


def diagnose(run_dir: Path, *, distance_threshold: float) -> dict:
    frames_dir = run_dir / "frames"
    if not frames_dir.is_dir():
        raise FileNotFoundError(f"{frames_dir} does not exist")
    pkls = sorted(frames_dir.glob("frame_*.pkl"))
    if not pkls:
        raise FileNotFoundError(f"no frame_*.pkl under {frames_dir}")

    n_pairs = 0
    n_flips = 0
    n_count_mismatch = 0
    n_dist_dropped = 0
    flip_examples: List[Tuple[str, str, float]] = []

    prev_hands: Optional[list] = None
    prev_name: str = ""
    for pkl in pkls:
        curr_hands = _load_hands(pkl)
        if curr_hands is None or prev_hands is None:
            prev_hands = curr_hands
            prev_name = pkl.stem
            continue
        if not prev_hands or not curr_hands:
            prev_hands = curr_hands
            prev_name = pkl.stem
            continue
        if len(prev_hands) != len(curr_hands):
            n_count_mismatch += 1
            prev_hands = curr_hands
            prev_name = pkl.stem
            continue

        matches = _greedy_match(prev_hands, curr_hands, max_dist=distance_threshold)
        n_dist_dropped += len(prev_hands) - len(matches)
        for i, j, d in matches:
            n_pairs += 1
            if bool(prev_hands[i].is_right) != bool(curr_hands[j].is_right):
                n_flips += 1
                if len(flip_examples) < 5:
                    flip_examples.append((prev_name, pkl.stem, d))

        prev_hands = curr_hands
        prev_name = pkl.stem

    return {
        "n_pairs": n_pairs,
        "n_flips": n_flips,
        "n_count_mismatch": n_count_mismatch,
        "n_dist_dropped": n_dist_dropped,
        "flip_examples": flip_examples,
        "n_frames": len(pkls),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path,
                    help="run_hand_estimation.py output directory (must contain frames/*.pkl)")
    ap.add_argument("--distance-threshold", type=float, default=50.0,
                    help="bbox-centre distance below which two hands are considered the same "
                         "physical hand across consecutive frames (pixels, default: 50)")
    args = ap.parse_args(argv)

    result = diagnose(args.run_dir, distance_threshold=args.distance_threshold)

    print(f"Scanned {result['n_frames']} frame pkls in {args.run_dir}/frames/")
    print(f"  excluded (different hand-count between frames): {result['n_count_mismatch']}")
    print(f"  excluded (bbox distance >= {args.distance_threshold}px): {result['n_dist_dropped']}")
    if result["flip_examples"]:
        print("  flip examples (prev → curr, distance):")
        for prev_name, curr_name, d in result["flip_examples"]:
            print(f"    {prev_name} → {curr_name} (d={d:.1f} px)")
    print()
    # Machine-readable summary block:
    n_pairs = result["n_pairs"]
    n_flips = result["n_flips"]
    rate = (n_flips / n_pairs) if n_pairs > 0 else 0.0
    print(f"Total adjacent-frame hand pairs: {n_pairs}")
    print(f"Flips:                            {n_flips}")
    print(f"Flip rate:                        {rate:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
