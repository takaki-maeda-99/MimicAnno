"""Artifact schema version constants (spec §6.6).

Each schema is independent. ``COMPAT_BLOCK`` is the producer-side declaration
of what MAJOR each in-run artifact was emitted at; consumers verify this against
their own ``supported_majors`` set membership (NOT >=).
"""

from __future__ import annotations


def parse_major(version: str) -> int:
    """Return the MAJOR of a ``MAJOR.MINOR.PATCH`` semver string."""
    major_str, _, _ = version.partition(".")
    return int(major_str)


ARTIFACT_SCHEMA_VERSIONS: dict[str, str] = {
    "manifest": "0.1.0",
    "annotation": "0.2.0",   # Phase 4 bump (spec §4.4): adds SubtaskSegment.smoothing_ops
    "boundaries": "0.1.0",
    "signals": "0.1.0",
}

# COMPAT scope per §6.6: in-run artifacts only. Labels YAML and index.json
# carry their own schema_version and are validated independently at load time.
COMPAT_BLOCK: dict[str, int] = {
    role: parse_major(version) for role, version in ARTIFACT_SCHEMA_VERSIONS.items()
}

LABELS_SCHEMA_VERSION = "0.1.0"
INDEX_SCHEMA_VERSION = "0.1.0"
