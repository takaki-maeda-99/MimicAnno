# mimicanno/labelset.py
"""Label-set YAML loader (spec §8.1 / §8.4)."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files as pkg_files
from pathlib import Path

import yaml

from mimicanno.hashing import sha256_file
from mimicanno.schema_versions import LABELS_SCHEMA_VERSION

RESERVED_PHASES: frozenset[str] = frozenset({"unlabeled", "unknown"})


class LabelSetError(Exception):
    pass


@dataclass(slots=True)
class Label:
    id: str
    verbs: list[str]
    requires_object: bool


@dataclass(slots=True)
class LabelSet:
    schema_version: str
    task_type: str
    labels: list[Label]
    unknown_task_fallback: str | None
    path: Path
    sha256: str  # "sha256:<hex>"

    def label_ids(self) -> set[str]:
        return {lbl.id for lbl in self.labels}


def default_labels_path(task_type: str = "manipulation") -> Path:
    """Return the absolute path of the bundled label YAML for ``task_type``."""
    res = pkg_files("mimicanno.configs.labels").joinpath(f"{task_type}.yaml")
    return Path(str(res))


def load_label_set(path: Path) -> LabelSet:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise LabelSetError(f"{path}: top-level must be a mapping")

    sv = raw.get("schema_version")
    # §6.6 set-membership check — only exact versions in SUPPORTED_LABEL_VERSIONS
    # are accepted; widening the supported set is an explicit decision, not
    # implicit (>=) compatibility.
    SUPPORTED_LABEL_VERSIONS: frozenset[str] = frozenset({LABELS_SCHEMA_VERSION})
    if not isinstance(sv, str):
        raise LabelSetError(f"{path}: schema_version must be a string, got {sv!r}")
    if sv not in SUPPORTED_LABEL_VERSIONS:
        raise LabelSetError(
            f"{path}: schema_version {sv!r} not in supported set "
            f"{sorted(SUPPORTED_LABEL_VERSIONS)} (this consumer's set)",
        )

    labels_raw = raw.get("labels") or []
    labels: list[Label] = []
    for item in labels_raw:
        if not isinstance(item, dict):
            raise LabelSetError(f"{path}: label entry is not a mapping: {item!r}")
        if "id" not in item:
            raise LabelSetError(f"{path}: label entry missing required 'id' field: {item!r}")
        lid = item["id"]
        if lid in RESERVED_PHASES:
            raise LabelSetError(
                f"{path}: label id {lid!r} is reserved (see spec §8.4)",
            )
        labels.append(Label(
            id=lid,
            verbs=list(item.get("verbs") or []),
            requires_object=bool(item.get("requires_object", False)),
        ))

    return LabelSet(
        schema_version=sv,
        task_type=raw.get("task_type", "unknown"),
        labels=labels,
        unknown_task_fallback=raw.get("unknown_task_fallback"),
        path=path,
        sha256="sha256:" + sha256_file(path),
    )
