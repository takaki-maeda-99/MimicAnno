# mimicanno/cli.py
"""mimicanno CLI entry (typer)."""

from __future__ import annotations

from pathlib import Path

import typer

from mimicanno import __version__
from mimicanno.config import (
    AnnotationConfig,
    BoundaryConfig,
    ModelConfig,
)
from mimicanno.errors import MimicAnnoError, write_error_json
from mimicanno.pipeline import AnnotateRequest, annotate_episode

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
    score_threshold: float = typer.Option(0.30, "--score-threshold"),
    merge_window_sec: float = typer.Option(0.10, "--merge-window-sec"),
) -> None:
    """Annotate a single LeRobot episode and publish a Phase-1 run directory."""
    cfg = AnnotationConfig(
        boundary=BoundaryConfig(
            weights={"gripper": 0.5, "velocity": 0.25, "acceleration": 0.15, "action": 0.1},
            thresholds={"gripper_delta": 0.3, "velocity_valley": 0.05},
            merge_window_sec=merge_window_sec,
            score_threshold=score_threshold,
            disabled_sources=[],
        ),
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
