# mimicanno/publish.py
"""Publish transaction (spec §4.4 / §6.5)."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from mimicanno.config import RUN_HASH_FALLBACK_PREFIX_LEN, run_hash_short
from mimicanno.locks import file_lock
from mimicanno.rundir import CANONICAL_SEPARATOR, RunPaths, canonical_name_for, is_collision
from mimicanno.runindex import IndexRow, upsert_row
from mimicanno.scavenger import (
    WriterMetadata,
    current_pid_start_time,
    scavenge_stale_dirs,
    write_writer_metadata,
    WRITER_METADATA_FILENAME,
)


LOCK_TIMEOUT_SEC: float = 30.0
DEFAULT_STALE_AGE_SEC: float = 24 * 3600.0


class PublishOutcome(Enum):
    PUBLISHED = "published"
    REUSED_LOCK_FREE = "reused_lock_free"
    REUSED_LOCKED = "reused_locked"


@dataclass(slots=True)
class PublishRequest:
    runs_root: Path
    episode_id: str
    config_hash: str
    input_hash: str
    run_hash: str
    task_text: str
    pipeline_phase: int
    generated_at: str
    force: bool = False
    config_hash_short: str = field(default="")
    input_hash_short: str = field(default="")

    def __post_init__(self) -> None:
        # Default the short fields to first-12 of the hex part.
        if not self.config_hash_short:
            self.config_hash_short = self.config_hash.removeprefix("sha256:")[:8]
        if not self.input_hash_short:
            self.input_hash_short = self.input_hash.removeprefix("sha256:")[:8]


def _existing_run_hash(run_dir: Path) -> str | None:
    manifest = run_dir / "manifest.json"
    if not manifest.exists():
        return None
    try:
        return json.loads(manifest.read_text()).get("run_hash")
    except (OSError, json.JSONDecodeError):
        return None


def publish(
    req: PublishRequest,
    *,
    write_artifacts: Callable[[Path], None],
    stale_age_sec: float = DEFAULT_STALE_AGE_SEC,
) -> PublishOutcome:
    """Execute the full §4.4 publish transaction.

    ``write_artifacts(tmp_dir)`` is called outside the lock to populate the
    tmp run directory. It MUST write a ``manifest.json`` with a ``run_hash``
    field matching ``req.run_hash``; the orchestrator does not generate
    manifests itself.
    """
    runs_root = req.runs_root
    runs_root.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()

    # Resolve canonical_name with collision extension if needed.
    name = canonical_name_for(req.episode_id, run_hash=req.run_hash)
    if is_collision(runs_root, canonical_name=name, expected_run_hash=req.run_hash):
        name = canonical_name_for(
            req.episode_id, run_hash=req.run_hash,
            length=RUN_HASH_FALLBACK_PREFIX_LEN,
        )

    paths = RunPaths(runs_root=runs_root, canonical_name=name, pid=pid)

    # §4.4 step 2: lock-free reuse short-circuit.
    if not req.force:
        existing = _existing_run_hash(paths.final)
        if existing == req.run_hash:
            return PublishOutcome.REUSED_LOCK_FREE

    # §4.4 step 3: heavy compute outside the lock, into .tmp.<pid>/ with .writer.json.
    paths.tmp.mkdir(parents=True, exist_ok=True)
    write_writer_metadata(paths.tmp, WriterMetadata(
        pid=pid,
        pid_start_time=current_pid_start_time(pid),
        canonical_name=name,
        kind="tmp",
        claimed_at=dt.datetime.now(tz=dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    ))
    try:
        write_artifacts(paths.tmp)

        # §4.4 contract: write_artifacts must produce a manifest with the expected run_hash.
        produced_hash = _existing_run_hash(paths.tmp)
        if produced_hash != req.run_hash:
            raise ValueError(
                f"write_artifacts produced manifest.run_hash={produced_hash!r} "
                f"but PublishRequest.run_hash={req.run_hash!r}; the contract requires they match.",
            )

        # §4.4 step 4-9: locked publish.
        lock_path = runs_root / "index.json.lock"
        with file_lock(lock_path, timeout_sec=LOCK_TIMEOUT_SEC):
            # Step 5: scavenger.
            scavenge_stale_dirs(runs_root, stale_age_sec=stale_age_sec)

            # Step 6: locked reuse re-check.
            if not req.force:
                existing = _existing_run_hash(paths.final)
                if existing == req.run_hash:
                    shutil.rmtree(paths.tmp, ignore_errors=True)
                    _self_heal_index(runs_root, req, name)
                    return PublishOutcome.REUSED_LOCKED

            # Step 7: run-directory replacement (§6.5).
            # 7a) remove .writer.json from the soon-to-be-final dir.
            writer_md = paths.tmp / WRITER_METADATA_FILENAME
            if writer_md.exists():
                writer_md.unlink()
            # 7b) backup existing final, then rename tmp → final, then upsert index.
            bak_created = False
            try:
                if paths.final.exists():
                    paths.final.rename(paths.bak)
                    bak_created = True
                    write_writer_metadata(paths.bak, WriterMetadata(
                        pid=pid,
                        pid_start_time=current_pid_start_time(pid),
                        canonical_name=name,
                        kind="bak",
                        claimed_at=dt.datetime.now(tz=dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                    ))
                # 7c) atomic rename tmp → final.
                paths.tmp.rename(paths.final)

                # Step 8: index upsert.
                upsert_row(runs_root / "index.json", IndexRow(
                    episode_id=req.episode_id,
                    run_hash=req.run_hash,
                    run_hash_short=run_hash_short(req.run_hash, length=len(name) - len(req.episode_id) - len(CANONICAL_SEPARATOR)),
                    config_hash_short=req.config_hash_short,
                    input_hash_short=req.input_hash_short,
                    manifest_url=f"{name}/manifest.json",
                    task_text=req.task_text,
                    pipeline_phase=req.pipeline_phase,
                    generated_at=req.generated_at,
                ))
            finally:
                # Step 9: rm -rf bak (always clean up, even if upsert raises).
                if bak_created and paths.bak.exists():
                    shutil.rmtree(paths.bak, ignore_errors=True)

        return PublishOutcome.PUBLISHED
    except Exception:
        # C1: clean up any partial tmp dir before re-raising.
        shutil.rmtree(paths.tmp, ignore_errors=True)
        raise


def _self_heal_index(
    runs_root: Path, req: PublishRequest, name: str,
) -> None:
    """If the index lost a row that disk says exists, re-insert it."""
    upsert_row(runs_root / "index.json", IndexRow(
        episode_id=req.episode_id,
        run_hash=req.run_hash,
        run_hash_short=run_hash_short(
            req.run_hash, length=len(name) - len(req.episode_id) - len(CANONICAL_SEPARATOR),
        ),
        config_hash_short=req.config_hash_short,
        input_hash_short=req.input_hash_short,
        manifest_url=f"{name}/manifest.json",
        task_text=req.task_text,
        pipeline_phase=req.pipeline_phase,
        generated_at=req.generated_at,
    ))
