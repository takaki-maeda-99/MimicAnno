"""SinkWriter protocol — abstract sink interface (Phase 5 Task 10, spec §1.2).

Concrete implementations (e.g. ``LeRobotV3SinkWriter``) take an output dir +
list of ``CanonicalEpisode`` + an ``ExportProfile`` and write the dataset
according to the sink-format contract.

The protocol exists so that the bulk orchestrator can hold a single typed
reference and dispatch to whichever writer the profile selected.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mimicanno.exports.canonical import CanonicalEpisode
    from mimicanno.exports.profile import ExportProfile


@runtime_checkable
class SinkWriter(Protocol):
    """Structural type for sink writers."""

    def write_all(
        self,
        *,
        out_dir: Path,
        episodes: list[CanonicalEpisode],
        profile: ExportProfile,
        source_dataset: Path,
    ) -> None:
        """Write the export under ``out_dir`` using ``episodes`` and ``profile``.

        ``source_dataset`` is the original dataset root; the writer reads source
        parquet files (per-episode data, per-episode metadata, info.json) from
        there. The writer is responsible for atomic individual writes; the
        caller is responsible for transaction-level atomicity (output_layout).
        """
        ...
