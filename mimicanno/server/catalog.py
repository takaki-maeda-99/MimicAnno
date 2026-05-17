"""U-A1 — Dataset catalog scanner (spec §2.1).

Scans ``data/`` for LeRobot v3 datasets and cross-references with ``runs/``
to compute annotated episode counts.

Run-set scoping mirrors master spec §2.0:
- A **run-set** is any direct subdir of runs_root that contains index.json.
- Bare canonical dirs at runs_root top level → synthetic ``__legacy__`` bucket.
- ``annotated_ep_count`` = union of distinct episode indices across ALL run-sets.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("mimicanno.server")

# Canonical name pattern: episode_id + "__" + run_hash_short
_CANONICAL_RE = re.compile(r"^(episode_\d+)__[A-Za-z0-9]+$")

# episode_id → episode index
_EPISODE_IDX_RE = re.compile(r"^episode_(\d+)$")


@dataclass
class RunRef:
    canonical: str
    run_hash: str
    run_set: str
    pipeline_phase: int
    generated_at: str


@dataclass
class EpisodeInfo:
    idx: int
    video_path: str
    parquet_path: str
    frame_count: int | None
    fps: float | None
    runs: list[RunRef] = field(default_factory=list)


@dataclass
class DatasetInfo:
    name: str
    path: str
    ep_count: int
    annotated_ep_count: int
    robot_hint: str | None
    task_text_hint: str | None
    videos_root: str | None
    last_modified: str


@dataclass
class DatasetDetail:
    name: str
    path: str
    episodes: list[EpisodeInfo]


def _read_info_json(dataset_root: Path) -> dict[str, Any]:
    """Read data/{name}/meta/info.json; return {} on missing."""
    info_path = dataset_root / "meta" / "info.json"
    if not info_path.exists():
        return {}
    try:
        return json.loads(info_path.read_text())  # type: ignore[no-any-return]
    except Exception:
        return {}


def _read_task_text_hint(dataset_root: Path) -> str | None:
    """Read first task text from data/{name}/meta/tasks.parquet (if available)."""
    tasks_path = dataset_root / "meta" / "tasks.parquet"
    if not tasks_path.exists():
        return None
    try:
        # Attempt pandas parquet read; fall back gracefully.
        import pandas as pd  # type: ignore[import-untyped]
        df = pd.read_parquet(tasks_path)
        if df.empty:
            return None
        # tasks.parquet typically has columns: task_index, task
        if "task" in df.columns:
            val = df["task"].iloc[0]
            return str(val) if val is not None else None
    except Exception:
        pass
    return None


def _last_modified_iso(dataset_root: Path) -> str:
    """Return ISO8601 UTC of the latest mtime under data/{name}/meta/."""
    meta_dir = dataset_root / "meta"
    if not meta_dir.is_dir():
        try:
            mtime = dataset_root.stat().st_mtime
        except OSError:
            mtime = 0.0
        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    latest = 0.0
    try:
        for p in meta_dir.iterdir():
            try:
                t = p.stat().st_mtime
                if t > latest:
                    latest = t
            except OSError:
                pass
    except OSError:
        pass
    return datetime.fromtimestamp(latest, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _extract_robot_hint(info: dict[str, Any]) -> str | None:
    """Infer robot hint from info.json robot_type field; null if 'unknown'."""
    rt = info.get("robot_type")
    if not isinstance(rt, str) or rt.lower() == "unknown":
        return None
    return rt


def _extract_videos_root(info: dict[str, Any]) -> str | None:
    """Extract the first video directory key from info.json features."""
    video_path_template = info.get("video_path", "")
    if not video_path_template:
        return None
    # Template: "videos/{video_key}/chunk-{chunk_index:03d}/episode_{episode_index:06d}.mp4"
    # Extract up to the first {video_key} replacement, i.e., take the prefix.
    # Alternatively, find a video feature key from features:
    features = info.get("features", {})
    for key, feat in features.items():
        if isinstance(feat, dict) and feat.get("dtype") == "video":
            # Build the path: "videos/chunk-000/{key}" or per template
            # Use the video_path_template if it contains {video_key}
            if "{video_key}" in video_path_template:
                # Build with chunk-000 and the key
                path = video_path_template.replace("{video_key}", key)
                path = path.replace("{chunk_index:03d}", "000")
                # Remove the episode filename part
                path = "/".join(path.split("/")[:-1])
                return path
    return None


def _collect_runs_from_runsets(
    runs_root: Path,
) -> dict[str, list[RunRef]]:
    """Scan runs_root and collect episode_id → [RunRef] from all run-sets.

    Returns a dict keyed by episode_id (e.g. "episode_000000").
    """
    ep_runs: dict[str, list[RunRef]] = {}

    if not runs_root.is_dir():
        return ep_runs

    def _add_from_index(index_path: Path, run_set_name: str) -> None:
        try:
            data = json.loads(index_path.read_text())
        except Exception:
            return
        for row in data.get("runs", []):
            episode_id = row.get("episode_id", "")
            canonical = row.get("canonical_name", "")
            # Derive canonical from manifest_url if not directly present
            if not canonical:
                murl = row.get("manifest_url", "")
                parts = murl.split("/")
                canonical = parts[0] if parts else ""
            run_hash = row.get("run_hash", "")
            pipeline_phase = row.get("pipeline_phase", 0)
            generated_at = row.get("generated_at", "")
            if not episode_id:
                continue
            ref = RunRef(
                canonical=canonical,
                run_hash=run_hash,
                run_set=run_set_name,
                pipeline_phase=pipeline_phase,
                generated_at=generated_at,
            )
            if episode_id not in ep_runs:
                ep_runs[episode_id] = []
            ep_runs[episode_id].append(ref)

    # Check if runs_root itself has index.json (legacy single-mode)
    if (runs_root / "index.json").exists():
        _add_from_index(runs_root / "index.json", "__legacy__")
        return ep_runs

    # Multi-mode: scan subdirectories for run-sets (contain index.json)
    # Also handle bare canonical dirs at top level → __legacy__
    legacy_canonicals: list[str] = []
    for entry in sorted(runs_root.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / "index.json").exists():
            _add_from_index(entry / "index.json", entry.name)
        else:
            # Bare canonical dir at top level (legacy)
            if _CANONICAL_RE.match(entry.name):
                legacy_canonicals.append(entry.name)

    # Build RunRef entries for legacy canonicals from their manifest.json
    for canonical in legacy_canonicals:
        manifest_path = runs_root / canonical / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            mdata = json.loads(manifest_path.read_text())
        except Exception:
            continue
        episode_id = mdata.get("episode_id", "")
        if not episode_id:
            # Derive from canonical name
            m = _CANONICAL_RE.match(canonical)
            if m:
                episode_id = m.group(1)
        if not episode_id:
            continue
        run_hash = mdata.get("run_hash", "")
        pipeline_phase = mdata.get("generator", {}).get("pipeline_phase", 0)
        generated_at = mdata.get("generated_at", "")
        ref = RunRef(
            canonical=canonical,
            run_hash=run_hash,
            run_set="__legacy__",
            pipeline_phase=pipeline_phase,
            generated_at=generated_at,
        )
        if episode_id not in ep_runs:
            ep_runs[episode_id] = []
        ep_runs[episode_id].append(ref)

    return ep_runs


def _ep_idx_from_id(episode_id: str) -> int | None:
    """Parse 'episode_000003' → 3."""
    m = _EPISODE_IDX_RE.match(episode_id)
    return int(m.group(1)) if m else None


def scan_datasets(data_root: Path, runs_root: Path) -> list[DatasetInfo]:
    """List all datasets under data_root with run-crossing annotated_ep_count."""
    if not data_root.is_dir():
        return []

    # Collect all runs across ALL run-sets (not dataset-specific)
    all_ep_runs = _collect_runs_from_runsets(runs_root)

    result: list[DatasetInfo] = []
    for dataset_dir in sorted(data_root.iterdir()):
        if not dataset_dir.is_dir():
            continue
        name = dataset_dir.name
        info = _read_info_json(dataset_dir)

        ep_count = info.get("total_episodes", 0)
        if not isinstance(ep_count, int):
            ep_count = 0

        robot_hint = _extract_robot_hint(info)
        task_text_hint = _read_task_text_hint(dataset_dir)
        videos_root = _extract_videos_root(info)
        last_modified = _last_modified_iso(dataset_dir)

        # annotated_ep_count: count distinct episodes that have ≥1 run
        # Use episode index range from ep_count to filter by dataset
        annotated_idxs: set[int] = set()
        for ep_id, refs in all_ep_runs.items():
            if not refs:
                continue
            idx = _ep_idx_from_id(ep_id)
            if idx is not None and 0 <= idx < ep_count:
                annotated_idxs.add(idx)

        result.append(DatasetInfo(
            name=name,
            path=f"data/{name}",
            ep_count=ep_count,
            annotated_ep_count=len(annotated_idxs),
            robot_hint=robot_hint,
            task_text_hint=task_text_hint,
            videos_root=videos_root,
            last_modified=last_modified,
        ))

    return result


def get_dataset_detail(
    name: str,
    data_root: Path,
    runs_root: Path,
) -> DatasetDetail | None:
    """Return per-episode detail for a dataset, or None if not found."""
    dataset_dir = data_root / name
    if not dataset_dir.is_dir():
        return None

    info = _read_info_json(dataset_dir)
    ep_count: int = info.get("total_episodes", 0)
    if not isinstance(ep_count, int):
        ep_count = 0

    fps_val = info.get("fps")
    fps: float | None = float(fps_val) if fps_val is not None else None

    # video_path template: "videos/{video_key}/chunk-{chunk_index:03d}/episode_{episode_index:06d}.mp4"
    video_path_template: str = info.get("video_path", "")
    data_path_template: str = info.get("data_path", "")

    # Find the first video feature key
    features = info.get("features", {})
    video_key: str | None = None
    for k, v in features.items():
        if isinstance(v, dict) and v.get("dtype") == "video":
            video_key = k
            break

    # Collect all runs for this dataset
    all_ep_runs = _collect_runs_from_runsets(runs_root)

    episodes: list[EpisodeInfo] = []
    for idx in range(ep_count):
        ep_id = f"episode_{idx:06d}"

        # Build file paths from templates
        if video_path_template and video_key:
            vpath = (
                video_path_template
                .replace("{video_key}", video_key)
                .replace("{chunk_index:03d}", "000")
                .replace("{episode_index:06d}", f"{idx:06d}")
            )
        else:
            vpath = f"videos/chunk-000/{ep_id}.mp4"

        if data_path_template:
            dpath = (
                data_path_template
                .replace("{chunk_index:03d}", "000")
                .replace("{episode_index:06d}", f"{idx:06d}")
            )
        else:
            dpath = f"data/chunk-000/{ep_id}.parquet"

        runs_for_ep = all_ep_runs.get(ep_id, [])
        episodes.append(EpisodeInfo(
            idx=idx,
            video_path=vpath,
            parquet_path=dpath,
            frame_count=None,  # would need parquet read; skip for now
            fps=fps,
            runs=runs_for_ep,
        ))

    return DatasetDetail(
        name=name,
        path=f"data/{name}",
        episodes=episodes,
    )
