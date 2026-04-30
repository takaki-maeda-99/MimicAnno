"""MimicAnno — robot episode subtask annotation pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mimicanno.__version__ import __version__

if TYPE_CHECKING:
    from mimicanno.exports.bulk import ExportResult as ExportResult
    from mimicanno.exports.profile import ExportProfile as ExportProfile


def export(
    *,
    dataset_root: str | Path,
    runs_root: str | Path,
    target_phase: int,
    profile: str | ExportProfile,
    out: str | Path,
    output_mode: str = "symlink",
    **kwargs: Any,
) -> ExportResult:
    """Phase 5 export entry point."""
    from mimicanno.exports.bulk import bulk_export as _bulk_export
    from mimicanno.exports.profile import ExportProfile as _ExportProfile
    p = profile if isinstance(profile, _ExportProfile) else _ExportProfile.resolve(profile)
    return _bulk_export(
        dataset_root=Path(dataset_root),
        runs_root=Path(runs_root),
        target_phase=target_phase,
        profile=p,
        out=Path(out),
        output_mode=output_mode,  # type: ignore[arg-type]
        **kwargs,
    )


def __getattr__(name: str) -> Any:
    if name == "ExportProfile":
        from mimicanno.exports.profile import ExportProfile as _ExportProfile
        return _ExportProfile
    if name == "ExportResult":
        from mimicanno.exports.bulk import ExportResult as _ExportResult
        return _ExportResult
    raise AttributeError(name)


__all__ = ["ExportProfile", "ExportResult", "__version__", "export"]
