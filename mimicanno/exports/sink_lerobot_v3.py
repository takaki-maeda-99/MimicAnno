"""LeRobot v3 sink writer (Phase 5 Tasks 10–16, spec §4).

Writes a fresh LeRobot v3 dataset under ``out_dir`` using a list of
``CanonicalEpisode`` and an ``ExportProfile``. Skeleton only at Task 10;
sub-writers are added in Tasks 11–15 and the integrator + post-write
validation lands in Task 16.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mimicanno.exports.canonical import CanonicalEpisode
    from mimicanno.exports.profile import ExportProfile


class LeRobotV3SinkWriter:
    """Writes a fresh LeRobot v3 dataset (spec §4)."""

    def write_all(
        self,
        *,
        out_dir: Path,
        episodes: list[CanonicalEpisode],
        profile: ExportProfile,
        source_dataset: Path,
    ) -> None:
        raise NotImplementedError(
            "LeRobotV3SinkWriter.write_all is not yet implemented (Phase 5 Task 16)"
        )
