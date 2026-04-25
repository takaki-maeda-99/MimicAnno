"""Run-directory path helpers — single source of truth for canonical_name (§4.1)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from mimicanno.config import (
    RUN_HASH_DEFAULT_PREFIX_LEN,
    RUN_HASH_FALLBACK_PREFIX_LEN,
    run_hash_short,
)

CANONICAL_SEPARATOR = "__"


def canonical_name_for(
    episode_id: str, *, run_hash: str, length: int = RUN_HASH_DEFAULT_PREFIX_LEN,
) -> str:
    return f"{episode_id}{CANONICAL_SEPARATOR}{run_hash_short(run_hash, length=length)}"


def extend_collision_suffix(episode_id: str, *, run_hash: str) -> str:
    return canonical_name_for(
        episode_id, run_hash=run_hash, length=RUN_HASH_FALLBACK_PREFIX_LEN,
    )


def parse_canonical_name(canonical_name: str) -> tuple[str, str]:
    if CANONICAL_SEPARATOR not in canonical_name:
        raise ValueError(f"missing canonical-name separator '__' in {canonical_name!r}")
    episode_id, _, hash_short = canonical_name.rpartition(CANONICAL_SEPARATOR)
    return episode_id, hash_short


@dataclass(slots=True)
class RunPaths:
    runs_root: Path
    canonical_name: str
    pid: int

    @property
    def final(self) -> Path:
        return self.runs_root / self.canonical_name

    @property
    def tmp(self) -> Path:
        return self.runs_root / f"{self.canonical_name}.tmp.{self.pid}"

    @property
    def bak(self) -> Path:
        return self.runs_root / f"{self.canonical_name}.bak.{self.pid}"


def is_collision(
    runs_root: Path, *, canonical_name: str, expected_run_hash: str,
) -> bool:
    """Return True iff ``runs/<canonical_name>/`` exists with a DIFFERENT run_hash.

    Used to drive the §4.1 collision-extension path. No-collision when the dir
    is absent or its manifest's run_hash matches.
    """
    final = runs_root / canonical_name
    manifest = final / "manifest.json"
    if not manifest.exists():
        return False
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("run_hash") != expected_run_hash


def find_run_dirs_for_episode(runs_root: Path, episode_id: str) -> list[Path]:
    if not runs_root.exists():
        return []
    prefix = f"{episode_id}{CANONICAL_SEPARATOR}"
    return sorted(p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(prefix))
