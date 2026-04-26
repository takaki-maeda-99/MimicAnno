"""runs/index.json read + upsert (spec §4.4)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from mimicanno.schema_versions import INDEX_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class IndexRow:
    episode_id: str
    run_hash: str  # full sha256:<hex>
    run_hash_short: str  # display only
    config_hash_short: str
    input_hash_short: str
    manifest_url: str
    task_text: str
    pipeline_phase: int
    generated_at: str


@dataclass(slots=True)
class IndexFile:
    schema_version: str
    rows: list[IndexRow]


def read_index(path: Path) -> IndexFile:
    if not path.exists():
        return IndexFile(schema_version=INDEX_SCHEMA_VERSION, rows=[])
    data = json.loads(path.read_text())
    rows = [IndexRow(**row) for row in data.get("runs", [])]
    return IndexFile(schema_version=data.get("schema_version", INDEX_SCHEMA_VERSION), rows=rows)


def write_index_atomic(path: Path, idx: IndexFile) -> None:
    payload = {
        "schema_version": idx.schema_version,
        "runs": [asdict(r) for r in idx.rows],
    }
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    tmp.replace(path)


def upsert_row(path: Path, row: IndexRow) -> None:
    """Read → upsert by full ``run_hash`` (the upsert key per §4.4) → atomic write.

    NOTE: Caller is expected to hold ``runs/index.json.lock`` when invoking
    this — the function does not acquire the lock itself.
    """
    idx = read_index(path)
    rows = [
        r for r in idx.rows if not (r.episode_id == row.episode_id and r.run_hash == row.run_hash)
    ]
    rows.append(row)
    rows.sort(key=lambda r: r.generated_at, reverse=True)
    write_index_atomic(path, IndexFile(schema_version=idx.schema_version, rows=rows))
