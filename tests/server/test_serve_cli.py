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
    import sys
    saved_modules = {k: v for k, v in sys.modules.items() if k.startswith("mimicanno.server")}
    for k in saved_modules:
        del sys.modules[k]
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
