"""Phase 5 B r1 — labelset endpoint dependency (spec §3.1).

Loads the label YAML once at app startup and exposes it via a small DI
handle. Tests inject a precomputed ``LabelSet`` without disk access.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mimicanno.labelset import LabelSet, default_labels_path, load_label_set


@dataclass(slots=True, frozen=True)
class LabelSetCache:
    """DI handle. Construct via :meth:`from_path` (production) or directly
    by passing an arbitrary :class:`mimicanno.labelset.LabelSet` (tests)."""

    ls: LabelSet

    @classmethod
    def from_path(cls, path: Path | None = None) -> LabelSetCache:
        """Load from disk. ``None`` → bundled ``manipulation.yaml``."""
        return cls(load_label_set(path or default_labels_path()))

    def to_response_dict(self) -> dict[str, Any]:
        """Spec §3.1 response shape: ``id`` + ``requires_object`` per label,
        plus ``labels_yaml_sha256`` for ETag cache keying."""
        return {
            "labels": [
                {"id": lbl.id, "requires_object": lbl.requires_object}
                for lbl in self.ls.labels
            ],
            "labels_yaml_sha256": self.ls.sha256,
        }
