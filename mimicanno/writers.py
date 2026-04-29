# mimicanno/writers.py
"""Atomic JSON writers + jsonschema validation for run-dir artifacts."""

from __future__ import annotations

import json
from importlib.resources import files as pkg_files
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]

from mimicanno.io import write_json_atomic as _atomic_write_json
from mimicanno.schema import (
    AnnotationResult,
    BoundaryCandidate,
    Manifest,
)
from mimicanno.schema_versions import ARTIFACT_SCHEMA_VERSIONS
from mimicanno.signals import SignalChannel

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def _load_schema(name: str) -> dict[str, Any]:
    if name not in _SCHEMA_CACHE:
        text = pkg_files("mimicanno.jsonschemas").joinpath(f"{name}.schema.json").read_text()
        _SCHEMA_CACHE[name] = json.loads(text)
    return _SCHEMA_CACHE[name]


def _validate(name: str, data: dict[str, Any]) -> None:
    jsonschema.validate(instance=data, schema=_load_schema(name))


def write_manifest_json(path: Path, manifest: Manifest) -> None:
    """Validate and atomically write a ``manifest.json`` artifact."""
    data = manifest.to_dict()
    _validate("manifest", data)
    _atomic_write_json(path, data)


def write_annotation_json(path: Path, annotation: AnnotationResult) -> None:
    """Validate and atomically write an ``annotation.json`` artifact."""
    data = annotation.to_dict()
    _validate("annotation", data)
    _atomic_write_json(path, data)


def write_boundaries_json(
    path: Path,
    *,
    episode_id: str,
    candidates: list[BoundaryCandidate],
) -> None:
    """Validate and atomically write a ``boundaries.json`` artifact."""
    data: dict[str, Any] = {
        "schema_version": ARTIFACT_SCHEMA_VERSIONS["boundaries"],
        "episode_id": episode_id,
        "candidates": [c.to_dict() for c in candidates],
    }
    _validate("boundaries", data)
    _atomic_write_json(path, data)


def write_signals_json(
    path: Path,
    *,
    episode_id: str,
    duration_sec: float,
    channels: list[SignalChannel],
) -> None:
    """Validate and atomically write a ``signals.json`` artifact."""
    data: dict[str, Any] = {
        "schema_version": ARTIFACT_SCHEMA_VERSIONS["signals"],
        "episode_id": episode_id,
        "duration_sec": duration_sec,
        "channels": [
            {
                "name": ch.name,
                "unit": ch.unit,
                "t0_sec": ch.t0_sec,
                "dt_sec": ch.dt_sec,
                "values": [float(x) for x in ch.values.tolist()],
            }
            for ch in channels
        ],
    }
    _validate("signals", data)
    _atomic_write_json(path, data)
