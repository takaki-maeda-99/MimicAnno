"""Pre-flight model resolution (spec §2.5)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mimicanno.errors import VLMModelNotFound
from mimicanno.preflight import (
    PreflightResult,
    SHA40_REGEX,
    resolve_vlm_model,
)


def _make_fixture(tmp_path: Path, body: dict) -> Path:
    p = tmp_path / "fixt.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


# ---- 40-hex sha path (Case A) ---------------------------------------------

def test_sha40_regex_recognizes_40_hex_only() -> None:
    assert SHA40_REGEX.match("a" * 40)
    assert SHA40_REGEX.match("0123456789abcdef0123456789abcdef01234567")
    assert not SHA40_REGEX.match("a" * 39)
    assert not SHA40_REGEX.match("a" * 41)
    assert not SHA40_REGEX.match("Z" * 40)


def test_resolve_explicit_sha_does_not_call_hf(monkeypatch: pytest.MonkeyPatch) -> None:
    sha = "a" * 40
    called: list[str] = []

    def fake_model_info(*args, **kwargs):  # type: ignore[no-untyped-def]
        called.append("hf")
        raise AssertionError("HF API must not be called when sha is explicit")

    monkeypatch.setattr("mimicanno.preflight._hf_model_info", fake_model_info)
    r = resolve_vlm_model(f"google/gemma-x@{sha}", offline=False)
    assert r == PreflightResult(model_id="google/gemma-x", resolved_checkpoint=sha)
    assert called == []


# ---- HF API path (Case B) -------------------------------------------------

def test_resolve_branch_name_calls_hf_and_returns_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    sha = "b" * 40

    def fake_model_info(model_id: str, revision: str | None) -> str:
        assert model_id == "google/gemma-x"
        assert revision == "main"
        return sha

    monkeypatch.setattr("mimicanno.preflight._hf_model_info", fake_model_info)
    r = resolve_vlm_model("google/gemma-x@main", offline=False)
    assert r.resolved_checkpoint == sha


def test_resolve_no_revision_calls_hf(monkeypatch: pytest.MonkeyPatch) -> None:
    sha = "c" * 40

    def fake_model_info(model_id: str, revision: str | None) -> str:
        assert revision is None
        return sha

    monkeypatch.setattr("mimicanno.preflight._hf_model_info", fake_model_info)
    r = resolve_vlm_model("google/gemma-x", offline=False)
    assert r.resolved_checkpoint == sha


def test_resolve_offline_without_explicit_sha_aborts() -> None:
    with pytest.raises(VLMModelNotFound) as ei:
        resolve_vlm_model("google/gemma-x", offline=True)
    assert "explicit 40-hex commit sha required" in ei.value.message


def test_resolve_offline_with_branch_aborts() -> None:
    with pytest.raises(VLMModelNotFound) as ei:
        resolve_vlm_model("google/gemma-x@main", offline=True)
    assert "explicit 40-hex" in ei.value.message


def test_resolve_hf_lookup_failure_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_model_info(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("network unreachable")

    monkeypatch.setattr("mimicanno.preflight._hf_model_info", fake_model_info)
    with pytest.raises(VLMModelNotFound) as ei:
        resolve_vlm_model("google/gemma-x", offline=False)
    assert "network unreachable" in ei.value.message


# ---- Fixture URI path (Case C) --------------------------------------------

def test_resolve_fixture_uri(tmp_path: Path) -> None:
    p = _make_fixture(tmp_path, {"model_identity": {}, "segments": {}})
    expected_sha = hashlib.sha256(p.read_bytes()).hexdigest()
    r = resolve_vlm_model(f"fixture://{p}", offline=True)
    assert r.model_id == "fixture"
    assert r.resolved_checkpoint == expected_sha
    assert r.fixture_path == p.resolve()


def test_resolve_fixture_uri_missing_file_aborts(tmp_path: Path) -> None:
    nope = tmp_path / "nope.json"
    with pytest.raises(VLMModelNotFound) as ei:
        resolve_vlm_model(f"fixture://{nope}", offline=False)
    assert "fixture file" in ei.value.message
