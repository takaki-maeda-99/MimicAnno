"""Deterministic builder for the ``mini_runs`` mimicanno run fixture.

Run with ``uv run python tests/exports/fixtures/build_mini_runs.py``. Produces
``tests/exports/fixtures/mini_runs/`` containing 3 Phase-4 mimicanno run dirs
(one per ``mini_so101`` episode) plus an ``index.json``. Each manifest +
annotation validates against the published JSON schemas; segments cover
``[0, num_frames - 1]`` without gaps using labels from the manipulation
labelset.

This script is paired with ``build_mini_so101.py`` — both write fixed-seed
deterministic output so re-running produces byte-identical artifacts (asserted
in ``test_fixtures.py``).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

# Match the dataset builder.
FPS = 15.0
NUM_EPISODES = 3
FRAMES_PER_EPISODE = 20
GENERATED_AT = "2026-04-30T12:00:00Z"
SCHEMA_VERSION = "1.0"
LABEL_VERSION = "manipulation.v1"

# Five segments covering frames [0, 19] inclusive without gap.
# Phases drawn from mimicanno/configs/labels/manipulation.yaml.
SEGMENT_PLAN: list[tuple[str, int, int]] = [
    ("idle",            0,  3),
    ("approach_object", 4,  8),
    ("grasp_object",    9, 12),
    ("lift_object",    13, 16),
    ("retreat",        17, 19),
]


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _hash_for(prefix: str, episode_index: int) -> str:
    return "sha256:" + _sha256_hex(f"{prefix}:mini_so101:ep{episode_index}")


def _short(h: str, n: int = 8) -> str:
    return h.removeprefix("sha256:")[:n]


def _segment_dict(
    *,
    episode_id: str,
    phase: str,
    start_frame: int,
    end_frame: int,
    seg_index: int,
) -> dict[str, Any]:
    start_time = start_frame / FPS
    end_time = end_frame / FPS
    boundary_score = 0.85 + 0.01 * seg_index  # deterministic, in [0, 1]
    overall = 0.80 + 0.01 * seg_index
    sources_start = ["episode_start"] if start_frame == 0 else ["gripper_delta"]
    sources_end = (
        ["episode_end"] if end_frame == FRAMES_PER_EPISODE - 1 else ["gripper_delta"]
    )
    return {
        "segment_id": f"{episode_id}_seg{seg_index:02d}",
        "episode_id": episode_id,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "start_time": start_time,
        "end_time": end_time,
        "phase": phase,
        "verb": None,
        "object": None,
        "target": None,
        "failure_flags": [],
        "label_source": "signals_only",
        "object_state_unavailable": True,
        "object_track_ids": [],
        "label_version": LABEL_VERSION,
        "start_boundary": {
            "candidate_id": None,
            "time": start_time,
            "sources": sources_start,
            "score": boundary_score,
        },
        "end_boundary": {
            "candidate_id": None,
            "time": end_time,
            "sources": sources_end,
            "score": boundary_score,
        },
        "boundary_confidence": boundary_score,
        "vlm_confidence": None,
        "overall_confidence": overall,
        "evidence": None,
        "reviewed": False,
        "reviewer_id": None,
        "smoothing_ops": [],
    }


def _build_manifest(
    *,
    episode_id: str,
    config_hash: str,
    input_hash: str,
    run_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "episode_id": episode_id,
        "task": {"text": "mini test", "version": None},
        "generated_at": GENERATED_AT,
        "generator": {
            "name": "mimicanno",
            "cli_version": "0.1.0",
            "pipeline_phase": 4,
        },
        "config_hash": config_hash,
        "input_hash": input_hash,
        "run_hash": run_hash,
        "model_versions": {},
        "pipeline_params": {},
        "inputs": {},
        "time_base": "frame",
        "fps": FPS,
        "duration_sec": FRAMES_PER_EPISODE / FPS,
        "pipeline_status": {
            "object_state_available": False,
            "degraded_from_phase": None,
            "degrade_reason": None,
        },
        "compat": {},
        "artifacts": [],
    }


def _build_annotation(
    *,
    episode_id: str,
    config_hash: str,
    input_hash: str,
    run_hash: str,
) -> dict[str, Any]:
    segments = [
        _segment_dict(
            episode_id=episode_id,
            phase=phase,
            start_frame=start,
            end_frame=end,
            seg_index=i,
        )
        for i, (phase, start, end) in enumerate(SEGMENT_PLAN)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "episode_id": episode_id,
        "task": {"text": "mini test", "version": None},
        "generated_at": GENERATED_AT,
        "generator": {
            "name": "mimicanno",
            "cli_version": "0.1.0",
            "pipeline_phase": 4,
        },
        "config_hash": config_hash,
        "input_hash": input_hash,
        "run_hash": run_hash,
        "model_versions": {},
        "pipeline_phase": 4,
        "pipeline_status": {
            "object_state_available": False,
            "degraded_from_phase": None,
            "degrade_reason": None,
        },
        "segments": segments,
        "boundaries_url": "boundaries.json",
        "signals_url": "signals.json",
        "notes": None,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def build(out_root: Path) -> None:
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    index_rows: list[dict[str, Any]] = []
    for ep in range(NUM_EPISODES):
        episode_id = f"episode_{ep:06d}"
        config_hash = _hash_for("config", ep)
        input_hash = _hash_for("input", ep)
        run_hash = _hash_for("run", ep)
        canonical = f"{episode_id}__{_short(run_hash, 8)}"

        run_dir = out_root / canonical
        run_dir.mkdir()

        manifest = _build_manifest(
            episode_id=episode_id,
            config_hash=config_hash,
            input_hash=input_hash,
            run_hash=run_hash,
        )
        annotation = _build_annotation(
            episode_id=episode_id,
            config_hash=config_hash,
            input_hash=input_hash,
            run_hash=run_hash,
        )
        _write_json(run_dir / "manifest.json", manifest)
        _write_json(run_dir / "annotation.json", annotation)
        # boundaries / signals stubs (referenced by URL only).
        (run_dir / "boundaries.json").write_text("{}\n", encoding="utf-8")
        (run_dir / "signals.json").write_text("{}\n", encoding="utf-8")

        index_rows.append(
            {
                "episode_id": episode_id,
                "run_hash": run_hash,
                "run_hash_short": _short(run_hash, 8),
                "config_hash_short": _short(config_hash, 8),
                "input_hash_short": _short(input_hash, 8),
                "manifest_url": f"{canonical}/manifest.json",
                "task_text": "mini test",
                "pipeline_phase": 4,
                "generated_at": GENERATED_AT,
            }
        )

    _write_json(
        out_root / "index.json",
        {"schema_version": SCHEMA_VERSION, "runs": index_rows},
    )


def main() -> None:
    here = Path(__file__).resolve().parent
    build(here / "mini_runs")


if __name__ == "__main__":
    main()
