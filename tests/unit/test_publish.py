# tests/unit/test_publish.py
import json
from pathlib import Path

import pytest

from mimicanno.publish import PublishOutcome, PublishRequest, publish
from mimicanno.runindex import read_index


def _request(runs_root: Path, run_hash: str, task: str = "pick") -> PublishRequest:
    return PublishRequest(
        runs_root=runs_root,
        episode_id="ep0",
        config_hash="sha256:" + "0" * 64,
        input_hash="sha256:" + "1" * 64,
        run_hash=run_hash,
        task_text=task,
        pipeline_phase=1,
        generated_at="2026-04-26T00:00:00Z",
        force=False,
    )


def _stub_writer(run_dir: Path) -> None:
    """Pretend artifact writer used by tests: drop a manifest with run_hash."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_hash": "sha256:" + "9" * 64, "schema_version": "0.1.0"}),
    )


def test_first_publish_creates_run_dir_and_index(tmp_path: Path):
    rh = "sha256:" + "9" * 64
    req = _request(tmp_path, rh)
    outcome = publish(req, write_artifacts=_stub_writer)
    assert outcome == PublishOutcome.PUBLISHED
    final = next(d for d in tmp_path.iterdir() if d.is_dir() and d.name.startswith("ep0__"))
    assert (final / "manifest.json").exists()
    assert not (final / ".writer.json").exists()  # writer.json removed before finalization
    idx = read_index(tmp_path / "index.json")
    assert any(r.run_hash == rh for r in idx.rows)


def test_second_publish_with_same_run_hash_reuses_lock_free(tmp_path: Path):
    rh = "sha256:" + "9" * 64
    publish(_request(tmp_path, rh), write_artifacts=_stub_writer)
    outcome = publish(_request(tmp_path, rh), write_artifacts=_stub_writer)
    assert outcome == PublishOutcome.REUSED_LOCK_FREE


def test_force_replaces_run_dir(tmp_path: Path):
    rh = "sha256:" + "9" * 64
    publish(_request(tmp_path, rh), write_artifacts=_stub_writer)
    req = _request(tmp_path, rh)
    req.force = True
    outcome = publish(req, write_artifacts=_stub_writer)
    assert outcome == PublishOutcome.PUBLISHED


def test_write_artifacts_failure_cleans_up_tmp(tmp_path: Path):
    rh = "sha256:" + "9" * 64
    req = _request(tmp_path, rh)

    def _failing_writer(run_dir: Path) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        # Don't write a manifest; the contract check will catch it as ValueError.
        raise RuntimeError("simulated I/O error")

    with pytest.raises(RuntimeError):
        publish(req, write_artifacts=_failing_writer)

    # No .tmp dir should remain.
    leftover = list(tmp_path.glob("ep0__*.tmp.*"))
    assert leftover == []


def test_publish_writes_canonical_name_into_manifest(tmp_path: Path):
    """Phase 5 B r1 spec §3.3: after publish, the on-disk manifest.json
    carries canonical_name equal to the resolved run dir name."""
    rh = "sha256:" + "9" * 64
    req = _request(tmp_path, rh)
    outcome = publish(req, write_artifacts=_stub_writer)
    assert outcome == PublishOutcome.PUBLISHED
    final = next(d for d in tmp_path.iterdir() if d.is_dir() and d.name.startswith("ep0__"))
    raw = json.loads((final / "manifest.json").read_text())
    assert raw["canonical_name"] == final.name


def test_publish_canonical_name_upsert_preserves_run_hash(tmp_path: Path):
    """The canonical_name upsert MUST NOT change manifest.run_hash —
    that invariant is what downstream reuse short-circuit relies on
    (publish.py:99-102 _existing_run_hash compare)."""
    rh = "sha256:" + "9" * 64
    req = _request(tmp_path, rh)
    publish(req, write_artifacts=_stub_writer)
    final = next(d for d in tmp_path.iterdir() if d.is_dir() and d.name.startswith("ep0__"))
    raw = json.loads((final / "manifest.json").read_text())
    assert raw["run_hash"] == rh  # invariant: hash field unchanged by upsert


def test_write_artifacts_run_hash_mismatch_raises(tmp_path: Path):
    rh_request = "sha256:" + "9" * 64
    rh_actual = "sha256:" + "1" * 64
    req = _request(tmp_path, rh_request)

    def _wrong_writer(run_dir: Path) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "manifest.json").write_text(
            json.dumps({"run_hash": rh_actual, "schema_version": "0.1.0"}),
        )

    with pytest.raises(ValueError, match="contract requires"):
        publish(req, write_artifacts=_wrong_writer)

    # And tmp is cleaned up.
    leftover = list(tmp_path.glob("ep0__*.tmp.*"))
    assert leftover == []
