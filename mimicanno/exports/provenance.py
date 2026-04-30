"""Write / read the ``.mimicanno-export.json`` provenance manifest (spec §8).

Phase 5 Task 21. The manifest records *every* input that affected this export
(profile hash, runs_used dict, source_dataset_path, runs_root, target_phase,
config_hash_filter, output_mode, mimicanno_version, generated_at, cli_args,
host) so that the bulk-export idempotency short-circuit (spec §9.1) and
downstream consumers can verify provenance.

Validated against ``mimicanno/jsonschemas/export_manifest.schema.json`` before
write; schema mismatch raises :class:`MimicAnnoError` with code
``EXPORT_INTERNAL_MANIFEST_INVALID`` (this is a mimicanno bug, not user input —
distinct from ``EXPORT_PROFILE_INVALID`` which surfaces malformed user
``--profile`` YAML).
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]

from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.exports.profile import ExportProfile
from mimicanno.io import write_json_atomic

EXPORT_MANIFEST_FILENAME = ".mimicanno-export.json"


def _load_schema() -> dict[str, Any]:
    text = (
        resources.files("mimicanno.jsonschemas")
        .joinpath("export_manifest.schema.json")
        .read_text()
    )
    return json.loads(text)  # type: ignore[no-any-return]


def write_export_manifest(
    out: Path,
    *,
    profile: ExportProfile,
    runs_used: dict[int, str],
    run_hashes: dict[int, str],
    source_dataset: Path,
    runs_root: Path,
    target_phase: int,
    config_hash_filter: str | None,
    output_mode: str,
    mimicanno_version: str,
    generated_at: str,
    cli_args: list[str],
    host: dict[str, str],
    episode_count: int,
    subtask_count: int,
    sidecar_schema_version: str = "1",
) -> Path:
    """Write ``out / .mimicanno-export.json`` per spec §8 and return its path."""
    payload: dict[str, Any] = {
        "schema_version": "1",
        "kind": "mimicanno.export",
        "profile": {
            "name": profile.name,
            "hash": profile.hash(),
            "schema_version": profile.schema_version,
        },
        "source_dataset_path": str(source_dataset),
        "runs_root": str(runs_root),
        "target_phase": target_phase,
        "config_hash_filter": config_hash_filter,
        "output_mode": output_mode,
        "runs_used": {str(k): v for k, v in runs_used.items()},
        "run_hashes": {str(k): v for k, v in run_hashes.items()},
        "episode_count": episode_count,
        "subtask_count": subtask_count,
        "sidecar_schema_version": sidecar_schema_version,
        "mimicanno_version": mimicanno_version,
        "generated_at": generated_at,
        "cli_args": list(cli_args),
        "host": dict(host),
    }

    try:
        jsonschema.Draft202012Validator(_load_schema()).validate(payload)
    except jsonschema.ValidationError as e:
        # This is mimicanno producing a manifest that doesn't validate
        # against its own schema — internal bug, NOT user input.
        raise MimicAnnoError(
            ErrorCode.EXPORT_INTERNAL_MANIFEST_INVALID,
            f"export manifest schema violation: {e.message}",
            {"json_path": list(e.absolute_path)},
        ) from e

    path = out / EXPORT_MANIFEST_FILENAME
    write_json_atomic(path, payload)
    return path


def read_export_manifest(out: Path) -> dict[str, Any] | None:
    """Read ``out / .mimicanno-export.json`` if it exists, else ``None``."""
    path = out / EXPORT_MANIFEST_FILENAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
