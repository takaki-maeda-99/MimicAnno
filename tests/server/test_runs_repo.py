"""Phase 5 A T3: RunsRepository allow-list + traversal guard + retry."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from mimicanno.server.errors import MimicAnnoHTTPError


# ----- read_index -----


def test_read_index_returns_bytes(tmp_runs_root: Path) -> None:
    from mimicanno.server.runs_repo import RunsRepository
    repo = RunsRepository(tmp_runs_root)
    body = repo.read_index()
    parsed = json.loads(body)
    assert parsed["schema_version"] == "0.1.0"
    assert isinstance(parsed["runs"], list)


def test_read_index_missing_raises_404_index_missing(runs_root_no_index: Path) -> None:
    from mimicanno.server.runs_repo import RunsRepository
    repo = RunsRepository(runs_root_no_index)
    with pytest.raises(MimicAnnoHTTPError) as ei:
        repo.read_index()
    assert ei.value.status == 404
    assert ei.value.code == "index_missing"


def test_read_index_retries_on_filenotfound(
    tmp_runs_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec §3.3: index.json read also retries (cover the rare gap where the
    index is being rewritten with rename-aside)."""
    from mimicanno.server import runs_repo as mod
    from mimicanno.server.runs_repo import RunsRepository

    calls = {"n": 0}
    real_read_bytes = Path.read_bytes

    def fake_read_bytes(self: Path) -> bytes:
        if self.name == "index.json" and calls["n"] < 2:
            calls["n"] += 1
            raise FileNotFoundError(self)
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)  # speed up retry

    repo = RunsRepository(tmp_runs_root)
    body = repo.read_index()
    assert calls["n"] == 2  # 2 transient failures, then success
    assert b'"runs"' in body


# ----- open_artifact (manifest with bytes, others path-only) -----


def test_open_artifact_manifest_returns_bytes_for_etag(
    tmp_runs_root: Path, canonical_name: str,
) -> None:
    from mimicanno.server.runs_repo import RunsRepository
    repo = RunsRepository(tmp_runs_root)
    path, body = repo.open_artifact(canonical_name, "manifest.json")
    assert path.name == "manifest.json"
    assert body is not None
    assert b'"run_hash"' in body  # caller computes ETag from this


def test_open_artifact_non_manifest_returns_path_only(
    tmp_runs_root: Path, canonical_name: str,
) -> None:
    """Spec §4.1 #20: non-manifest artifacts must be streamed via FileResponse,
    so the repo should return a path without slurping the bytes."""
    from mimicanno.server.runs_repo import RunsRepository
    repo = RunsRepository(tmp_runs_root)
    path, body = repo.open_artifact(canonical_name, "boundaries.json")
    assert path.exists()
    assert body is None


def test_open_artifact_allow_list_rejects_video(
    tmp_runs_root: Path, canonical_name: str,
) -> None:
    """video.mp4 is not in the allow-list (spec §3.3)."""
    from mimicanno.server.runs_repo import RunsRepository
    repo = RunsRepository(tmp_runs_root)
    with pytest.raises(MimicAnnoHTTPError) as ei:
        repo.open_artifact(canonical_name, "video.mp4")
    assert ei.value.status == 404
    assert ei.value.code == "artifact_not_found"


def test_open_artifact_invalid_canonical_name(tmp_runs_root: Path) -> None:
    """canonical_name regex rejects `..` and special chars upfront (spec §3.3)."""
    from mimicanno.server.runs_repo import RunsRepository
    repo = RunsRepository(tmp_runs_root)
    for bad in ("../etc", "name with space", "name/with/slash", "name%2E"):
        with pytest.raises(MimicAnnoHTTPError) as ei:
            repo.open_artifact(bad, "manifest.json")
        assert ei.value.status == 400
        assert ei.value.code == "invalid_name"


def test_open_artifact_symlink_escape_rejected(
    tmp_runs_root: Path, canonical_name: str, tmp_path: Path,
) -> None:
    """Spec §3.3: even if a name passes the allow-list, ``resolve()`` +
    ``is_relative_to(runs_root)`` rejects symlinks pointing outside the root."""
    from mimicanno.server.runs_repo import RunsRepository
    # Replace boundaries.json with a symlink targeting /etc/passwd-ish.
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    art = tmp_runs_root / canonical_name / "boundaries.json"
    art.unlink()
    art.symlink_to(outside)

    repo = RunsRepository(tmp_runs_root)
    with pytest.raises(MimicAnnoHTTPError) as ei:
        repo.open_artifact(canonical_name, "boundaries.json")
    assert ei.value.status == 404
    assert ei.value.code == "artifact_not_found"


def test_open_artifact_missing_run_dir_returns_404(
    tmp_runs_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3× retry with 100ms sleep, then 404 ``run_not_found`` (spec §3.3)."""
    from mimicanno.server import runs_repo as mod
    from mimicanno.server.runs_repo import RunsRepository

    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    repo = RunsRepository(tmp_runs_root)
    with pytest.raises(MimicAnnoHTTPError) as ei:
        repo.open_artifact("episode_999999__nonexistent", "manifest.json")
    assert ei.value.status == 404
    assert ei.value.code == "run_not_found"


def test_open_artifact_retries_then_succeeds(
    tmp_runs_root: Path, canonical_name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inject 2× transient FileNotFoundError, expect 3rd attempt to succeed.
    Simulates the publish dir-gap window."""
    from mimicanno.server import runs_repo as mod
    from mimicanno.server.runs_repo import RunsRepository

    real_read_bytes = Path.read_bytes
    calls = {"n": 0}

    def fake_read_bytes(self: Path) -> bytes:
        if self.name == "manifest.json" and calls["n"] < 2:
            calls["n"] += 1
            raise FileNotFoundError(self)
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    repo = RunsRepository(tmp_runs_root)
    path, body = repo.open_artifact(canonical_name, "manifest.json")
    assert calls["n"] == 2
    assert body is not None


def test_open_artifact_retry_exhausted_then_404(
    tmp_runs_root: Path, canonical_name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3× FileNotFoundError → 404 ``run_not_found``."""
    from mimicanno.server import runs_repo as mod
    from mimicanno.server.runs_repo import RunsRepository

    def always_missing(self: Path) -> bytes:
        if self.name == "manifest.json":
            raise FileNotFoundError(self)
        return b"{}"  # other reads pass

    monkeypatch.setattr(Path, "read_bytes", always_missing)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    repo = RunsRepository(tmp_runs_root)
    with pytest.raises(MimicAnnoHTTPError) as ei:
        repo.open_artifact(canonical_name, "manifest.json")
    assert ei.value.status == 404
    assert ei.value.code == "run_not_found"
