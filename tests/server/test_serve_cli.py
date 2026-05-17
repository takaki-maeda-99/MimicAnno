"""Phase 5 A T6: ``mimicanno serve`` CLI subprocess integration test."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import httpx
import pytest


_READY_TIMEOUT_SEC = 15.0
_READY_POLL_SEC = 0.2


def _wait_until_ready(port: int, timeout: float = _READY_TIMEOUT_SEC) -> None:
    deadline = time.monotonic() + timeout
    last_err: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1.0)
            if r.status_code == 200:
                return
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            last_err = exc
        time.sleep(_READY_POLL_SEC)
    raise RuntimeError(
        f"serve never became ready on port {port} (last error: {last_err})",
    )


@pytest.mark.integration
def test_serve_cli_end_to_end(
    tmp_runs_root: Path, canonical_name: str, free_port: int,
) -> None:
    """Spawn ``mimicanno serve`` as a subprocess, hit each endpoint,
    then SIGTERM and wait for graceful shutdown."""
    env = os.environ.copy()
    # Defensive: drop any developer-set reviewer so the subprocess is
    # deterministic regardless of the host env (T9 added env consumption).
    env.pop("MIMICANNO_REVIEWER", None)
    proc = subprocess.Popen(
        [
            "uv", "run", "--extra", "server", "mimicanno", "serve",
            "--runs-root", str(tmp_runs_root),
            "--host", "127.0.0.1",
            "--port", str(free_port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        _wait_until_ready(free_port)
        base = f"http://127.0.0.1:{free_port}"
        assert httpx.get(f"{base}/healthz").status_code == 200
        r_index = httpx.get(f"{base}/api/runs/index.json")
        assert r_index.status_code == 200
        assert r_index.json()["schema_version"] == "0.1.0"
        r_mani = httpx.get(f"{base}/api/runs/{canonical_name}/manifest.json")
        assert r_mani.status_code == 200
        assert r_mani.headers.get("etag", "").startswith('"sha256:')
    finally:
        # Graceful shutdown.
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    assert proc.returncode is not None


def test_serve_cli_missing_extra_message(
    tmp_runs_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If fastapi can't be imported the CLI exits with a friendly message."""
    # Hide fastapi from the import system so serve_cmd's try/except fires.
    # IMPORTANT: use monkeypatch.delitem so sys.modules entries are
    # auto-restored after the test — bare `del sys.modules[k]` leaves
    # mimicanno.server.* in a torn state, breaking later monkeypatch.setattr
    # against those dotted paths (T9 regression).
    import sys
    for k in list(sys.modules):
        if k.startswith("mimicanno.server"):
            monkeypatch.delitem(sys.modules, k, raising=False)
    import builtins
    real_import = builtins.__import__

    def fake_import(name: str, *a: object, **kw: object):  # type: ignore[no-untyped-def]
        if name == "uvicorn" or name.startswith("mimicanno.server"):
            raise ImportError(f"forced missing {name}")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    from typer.testing import CliRunner
    from mimicanno.cli import app as cli_app

    runner = CliRunner()
    result = runner.invoke(
        cli_app, ["serve", "--runs-root", str(tmp_runs_root)],
    )
    assert result.exit_code == 2
    assert "uv sync --extra server" in (result.stderr or result.stdout)


# ----------------------------------------------------------------------------
# T9 — MIMICANNO_REVIEWER env passthrough (programmatic; subprocess test
# above is already env-deterministic via env.pop)
# ----------------------------------------------------------------------------


def _capture_reviewer(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Patch create_app + uvicorn.run as spies, return a dict the test
    can read after invoking the CLI."""
    captured: dict = {}

    def fake_create_app(*, runs_root, cors_origins, reviewer=None, labelset=None, hands_root=None, repo_root=None, jobs_dir=None, data_root=None, num_gpus=1):
        captured["reviewer"] = reviewer
        return "fake_app"

    def fake_uvicorn_run(app, **kwargs):  # noqa: ANN001 — spy
        captured["uvicorn_called"] = True

    monkeypatch.setattr(
        "mimicanno.server.app.create_app", fake_create_app,
    )
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)
    return captured


def test_serve_cmd_reads_reviewer_env_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """T9: MIMICANNO_REVIEWER="alice" reaches create_app(reviewer="alice")."""
    captured = _capture_reviewer(monkeypatch)
    monkeypatch.setenv("MIMICANNO_REVIEWER", "alice")
    from typer.testing import CliRunner
    from mimicanno.cli import app as cli_app
    result = CliRunner().invoke(
        cli_app, ["serve", "--runs-root", str(tmp_path), "--port", "12345"],
    )
    assert result.exit_code == 0
    assert captured["reviewer"] == "alice"
    assert captured.get("uvicorn_called") is True


def test_serve_cmd_reviewer_env_unset_means_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """T9: env unset → reviewer=None."""
    captured = _capture_reviewer(monkeypatch)
    monkeypatch.delenv("MIMICANNO_REVIEWER", raising=False)
    from typer.testing import CliRunner
    from mimicanno.cli import app as cli_app
    result = CliRunner().invoke(
        cli_app, ["serve", "--runs-root", str(tmp_path), "--port", "12345"],
    )
    assert result.exit_code == 0
    assert captured["reviewer"] is None


def test_serve_cmd_reviewer_env_empty_means_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """T9: empty string → reviewer=None (matches T6h hash normalisation)."""
    captured = _capture_reviewer(monkeypatch)
    monkeypatch.setenv("MIMICANNO_REVIEWER", "")
    from typer.testing import CliRunner
    from mimicanno.cli import app as cli_app
    result = CliRunner().invoke(
        cli_app, ["serve", "--runs-root", str(tmp_path), "--port", "12345"],
    )
    assert result.exit_code == 0
    assert captured["reviewer"] is None


def test_serve_cmd_reviewer_env_whitespace_only_means_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """T9 (review-flagged edge): whitespace-only env → None (.strip() guard)."""
    captured = _capture_reviewer(monkeypatch)
    monkeypatch.setenv("MIMICANNO_REVIEWER", "   ")
    from typer.testing import CliRunner
    from mimicanno.cli import app as cli_app
    result = CliRunner().invoke(
        cli_app, ["serve", "--runs-root", str(tmp_path), "--port", "12345"],
    )
    assert result.exit_code == 0
    assert captured["reviewer"] is None
