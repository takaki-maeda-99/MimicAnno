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
    VLMConfig,
    load_boundary_config_yaml,
)
from mimicanno.errors import (  # noqa: E402
    MimicAnnoError,
    VLMConfigInvalid,
    VLMModelRequired,
    write_error_json,
)
from mimicanno.pipeline import AnnotateRequest, annotate_episode  # noqa: E402
from mimicanno.preflight import resolve_vlm_model  # noqa: E402

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
    target_phase: int = typer.Option(
        1, "--target-phase",
        help="1 = boundaries+segments only; 2 = +VLM phase labeling.",
    ),
    vlm_model: str | None = typer.Option(
        None, "--vlm-model",
        help="HF model_id, '<id>@<sha>', or 'fixture://<path>'. Required when --target-phase >= 2.",
    ),
    vlm_keyframes: int = typer.Option(
        4, "--vlm-keyframes",
        help="Keyframes per segment passed to the VLM (>= 1).",
    ),
    vlm_max_retries: int = typer.Option(
        3, "--vlm-max-retries",
        help="Max attempts per segment before unknown_fallback.",
    ),
    offline: bool = typer.Option(
        False, "--offline",
        help="Forbid HF Hub network access; --vlm-model MUST include @<sha>.",
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

    # Phase 2 prerequisites: resolve --vlm-model via pre-flight (§2.5).
    vlm_config: VLMConfig | None = None
    if target_phase >= 2:
        if vlm_model is None:
            try:
                raise VLMModelRequired(target_phase=target_phase)
            except MimicAnnoError as e:
                write_error_json(e)
                raise typer.Exit(code=2) from None
        try:
            preflight = resolve_vlm_model(vlm_model, offline=offline)
        except MimicAnnoError as e:
            write_error_json(e)
            raise typer.Exit(code=2) from None
        vlm_config = VLMConfig(
            model_id=preflight.model_id,
            resolved_checkpoint=preflight.resolved_checkpoint,
            fixture_path=preflight.fixture_path,
            keyframes_per_segment=vlm_keyframes,
            max_retries=vlm_max_retries,
        )
        if vlm_config.keyframes_per_segment < 1:
            try:
                raise VLMConfigInvalid(reason="--vlm-keyframes must be >= 1")
            except MimicAnnoError as e:
                write_error_json(e)
                raise typer.Exit(code=2) from None

    cfg = AnnotationConfig(
        boundary=boundary,
        target_phase=target_phase,
        model_config=ModelConfig(
            vlm_config.model_id if vlm_config else None,
            vlm_config.resolved_checkpoint if vlm_config else None,
            None,
            None,
        ),
        vlm=vlm_config,
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
