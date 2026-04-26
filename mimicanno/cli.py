# mimicanno/cli.py
"""mimicanno CLI entry (typer)."""

from __future__ import annotations

import sys
from pathlib import Path

# pyproject requires Python >= 3.11 (we use datetime.UTC and dict|None unions
# in expression context). Failing here gives a friendly message instead of an
# obscure AttributeError later; system pythons that ignore the dep marker
# (e.g. /usr/bin/python3.10) still get a clean exit.
_MIN_PY = (3, 11)
if sys.version_info[:2] < _MIN_PY:  # pragma: no cover — runtime guard
    sys.stderr.write(
        f"mimicanno requires Python >= {_MIN_PY[0]}.{_MIN_PY[1]} "
        f"(got {sys.version_info.major}.{sys.version_info.minor}). "
        "Use the project's .venv or a 3.11+ interpreter.\n"
    )
    raise SystemExit(2)

import typer  # noqa: E402

from mimicanno import __version__  # noqa: E402
from mimicanno.config import (  # noqa: E402
    AnnotationConfig,
    BoundaryConfig,
    ModelConfig,
    load_boundary_config_yaml,
)
from mimicanno.errors import MimicAnnoError, write_error_json  # noqa: E402
from mimicanno.pipeline import AnnotateRequest, annotate_episode  # noqa: E402

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("version")
def version_cmd() -> None:
    """Show the mimicanno version and exit."""
    typer.echo(__version__)


@app.command("annotate")
def annotate(
    video: Path = typer.Option(..., "--video", exists=True, dir_okay=False),
    parquet: Path = typer.Option(..., "--parquet", dir_okay=False),
    task: str = typer.Option(..., "--task"),
    robot: str = typer.Option(..., "--robot", help="Adapter: aloha | koch | so100 | generic"),
    robot_config: Path | None = typer.Option(None, "--robot-config"),
    labels: Path | None = typer.Option(None, "--labels-file"),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
    link_video: bool = typer.Option(False, "--link-video", help="Symlink video instead of copy"),
    force: bool = typer.Option(False, "--force", help="Replace existing run"),
    boundary_config: Path | None = typer.Option(
        None,
        "--boundary-config",
        exists=True,
        dir_okay=False,
        help="YAML overriding BoundaryConfig fields (weights/thresholds/merge_window_sec/"
        "score_threshold/disabled_sources). Missing fields fall back to spec §4.3 defaults. "
        "Per-flag --score-threshold / --merge-window-sec override values from this file.",
    ),
    score_threshold: float | None = typer.Option(
        None,
        "--score-threshold",
        help="Overrides score_threshold from --boundary-config / defaults (0.30).",
    ),
    merge_window_sec: float | None = typer.Option(
        None,
        "--merge-window-sec",
        help="Overrides merge_window_sec from --boundary-config / defaults (0.10).",
    ),
) -> None:
    """Annotate a single LeRobot episode and publish a Phase-1 run directory."""
    try:
        boundary = (
            load_boundary_config_yaml(boundary_config)
            if boundary_config is not None
            else BoundaryConfig.with_defaults()
        )
    except MimicAnnoError as e:
        write_error_json(e)
        raise typer.Exit(code=2) from None
    if score_threshold is not None:
        boundary.score_threshold = score_threshold
    if merge_window_sec is not None:
        boundary.merge_window_sec = merge_window_sec
    cfg = AnnotationConfig(
        boundary=boundary,
        target_phase=1,
        model_config=ModelConfig(None, None, None, None),
    )
    req = AnnotateRequest(
        video=video,
        parquet=parquet,
        task=task,
        robot_adapter_name=robot,
        robot_adapter_config_path=robot_config,
        labels_path=labels,
        runs_root=runs_root,
        link_video=link_video,
        force=force,
        config=cfg,
    )
    try:
        annotate_episode(req)
    except MimicAnnoError as e:
        write_error_json(e)
        raise typer.Exit(code=2) from None
    except Exception as e:  # pragma: no cover — last-resort safety net
        write_error_json(
            MimicAnnoError(
                code="internal.unhandled",
                message=str(e),
                context={"type": type(e).__name__},
            )
        )
        raise typer.Exit(code=3) from e


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover — invoked via `python -m mimicanno.cli`
    main()
