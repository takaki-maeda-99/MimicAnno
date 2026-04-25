from pathlib import Path

import pytest

from mimicanno.rundir import (
    RunPaths,
    canonical_name_for,
    extend_collision_suffix,
    find_run_dirs_for_episode,
    is_collision,
    parse_canonical_name,
)


class TestCanonicalName:
    def test_default_is_12_hex(self):
        n = canonical_name_for("episode_000", run_hash="sha256:" + "9f31a2bc4a77" + "0" * 52)
        assert n == "episode_000__9f31a2bc4a77"

    def test_extended_is_16_hex(self):
        n = canonical_name_for(
            "ep_x", run_hash="sha256:" + "abcdef0123456789" + "0" * 48, length=16,
        )
        assert n == "ep_x__abcdef0123456789"


class TestParseCanonicalName:
    def test_roundtrip(self):
        episode_id, hash_short = parse_canonical_name("episode_000__9f31a2bc4a77")
        assert episode_id == "episode_000"
        assert hash_short == "9f31a2bc4a77"

    def test_rejects_no_separator(self):
        with pytest.raises(ValueError, match="separator"):
            parse_canonical_name("episode_000")


class TestRunPaths:
    def test_paths(self, tmp_path: Path):
        rp = RunPaths(runs_root=tmp_path, canonical_name="ep0__abcdef012345", pid=12345)
        assert rp.final == tmp_path / "ep0__abcdef012345"
        assert rp.tmp == tmp_path / "ep0__abcdef012345.tmp.12345"
        assert rp.bak == tmp_path / "ep0__abcdef012345.bak.12345"


class TestCollision:
    def test_no_existing_no_collision(self, tmp_path: Path):
        assert not is_collision(tmp_path, canonical_name="ep0__abc",
                                expected_run_hash="sha256:" + "0" * 64)

    def test_existing_with_matching_hash_no_collision(self, tmp_path: Path):
        d = tmp_path / "ep0__abc"
        d.mkdir()
        (d / "manifest.json").write_text(
            '{"run_hash":"sha256:' + "0" * 64 + '"}',
        )
        assert not is_collision(
            tmp_path, canonical_name="ep0__abc",
            expected_run_hash="sha256:" + "0" * 64,
        )

    def test_existing_with_different_hash_is_collision(self, tmp_path: Path):
        d = tmp_path / "ep0__abc"
        d.mkdir()
        (d / "manifest.json").write_text(
            '{"run_hash":"sha256:' + "1" * 64 + '"}',
        )
        assert is_collision(
            tmp_path, canonical_name="ep0__abc",
            expected_run_hash="sha256:" + "0" * 64,
        )


def test_extend_collision_suffix():
    h = "sha256:" + "abcdef0123456789" + "0" * 48
    assert extend_collision_suffix("ep0", run_hash=h) == "ep0__abcdef0123456789"


def test_find_run_dirs_returns_empty_when_runs_root_missing(tmp_path: Path):
    missing = tmp_path / "does_not_exist"
    assert find_run_dirs_for_episode(missing, "ep0") == []
