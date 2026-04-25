import json
from pathlib import Path

from mimicanno.runindex import IndexRow, read_index, upsert_row


def _row(run_hash: str, *, episode: str = "ep0", task: str = "pick") -> IndexRow:
    return IndexRow(
        episode_id=episode,
        run_hash=run_hash,
        run_hash_short=run_hash.removeprefix("sha256:")[:12],
        config_hash_short="abc12345",
        input_hash_short="def67890",
        manifest_url=f"{episode}__{run_hash.removeprefix('sha256:')[:12]}/manifest.json",
        task_text=task,
        pipeline_phase=1,
        generated_at="2026-04-26T00:00:00Z",
    )


def test_read_empty_returns_empty_list(tmp_path: Path):
    idx = read_index(tmp_path / "index.json")
    assert idx.rows == []


def test_upsert_appends_new_row(tmp_path: Path):
    p = tmp_path / "index.json"
    upsert_row(p, _row("sha256:" + "a" * 64))
    data = json.loads(p.read_text())
    assert len(data["runs"]) == 1
    assert data["schema_version"] == "0.1.0"


def test_upsert_replaces_existing_by_full_run_hash(tmp_path: Path):
    p = tmp_path / "index.json"
    upsert_row(p, _row("sha256:" + "a" * 64, task="old"))
    upsert_row(p, _row("sha256:" + "a" * 64, task="new"))
    data = json.loads(p.read_text())
    assert len(data["runs"]) == 1
    assert data["runs"][0]["task_text"] == "new"


def test_upsert_appends_when_run_hash_differs(tmp_path: Path):
    p = tmp_path / "index.json"
    upsert_row(p, _row("sha256:" + "a" * 64))
    upsert_row(p, _row("sha256:" + "b" * 64))
    data = json.loads(p.read_text())
    assert len(data["runs"]) == 2
