# mimicanno/cli.py
"""mimicanno CLI entry (typer)."""

from __future__ import annotations

import json
import os
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

from dataclasses import replace  # noqa: E402

import typer  # noqa: E402

from mimicanno import __version__  # noqa: E402
from mimicanno.config import (  # noqa: E402
    AnnotationConfig,
    BoundaryConfig,
    SmootherConfig,
    TrackingConfig,
    VLMConfig,
    build_model_config,
    load_boundary_config_yaml,
    load_smoother_config_yaml,
)
from mimicanno.errors import (  # noqa: E402
    ErrorCode,
    MimicAnnoError,
    MissingDependencyError,
    VLMConfigInvalid,
    VLMModelRequired,
    write_error_json,
)
from mimicanno.exports.bulk import bulk_export  # noqa: E402
from mimicanno.exports.profile import ExportProfile  # noqa: E402
from mimicanno.pipeline import (  # noqa: E402
    AnnotateRequest,
    annotate_episode,
    annotate_episode_phase3,
    annotate_episode_phase4,
)
from mimicanno.preflight import resolve_sam3_checkpoint, resolve_vlm_model  # noqa: E402

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
    vlm_device: str | None = typer.Option(
        None, "--vlm-device",
        help="Device for VLM model load (cpu|cuda|cuda:N). Default: VLMConfig "
             "default (cuda). Use cpu when no GPU or driver mismatch.",
    ),
    vlm_timeout_sec: float | None = typer.Option(
        None, "--vlm-timeout-sec",
        help="Per-attempt inference timeout (sec). Default: VLMConfig default "
             "(30s, sized for GPU). Bump to 300+ for CPU runs.",
    ),
    vlm_mask_overlay: bool = typer.Option(
        True, "--vlm-mask-overlay/--no-vlm-mask-overlay",
        help="Paint SAM3 masks on the keyframes shown to Gemma and "
             "include a color legend in the prompt (spec "
             "2026-05-04-vlm-mask-overlay-design). Disabling reverts "
             "to plain keyframes; the run is still valid but loses the "
             "overlay-conditioned label boost.",
    ),
    vlm_mask_alpha: float = typer.Option(
        0.4, "--vlm-mask-alpha",
        help="Opacity of the mask overlay paint (0.0..1.0). Ignored when "
             "--no-vlm-mask-overlay is set. The legend wording uses "
             "'~40% opacity' regardless so values nearby (0.3..0.5) are "
             "drop-in.",
    ),
    offline: bool = typer.Option(
        False, "--offline",
        help="Forbid HF Hub network access; --vlm-model MUST include @<sha>.",
    ),
    sam3_checkpoint: Path | None = typer.Option(
        None, "--sam3-checkpoint", dir_okay=False,
        help="Path to SAM3 weights file (e.g., sam3/checkpoints/sam3.pt). "
             "Required when --target-phase >= 3.",
    ),
    sam3_offload: bool = typer.Option(
        True, "--sam3-offload/--no-sam3-offload",
        help="Offload sam3 video tensors to CPU between forward passes "
             "(default: on). Each tracked prompt opens its own session, so "
             "without offload long episodes can OOM the GPU. Disable only "
             "for short videos where latency matters more than memory.",
    ),
    track_stride_frames: int | None = typer.Option(
        None, "--track-stride-frames",
        help="SAM3 video propagation stride (frames). Default: TrackingConfig.effective_stride.",
    ),
    smoother_config: Path | None = typer.Option(
        None, "--smoother-config", exists=True, dir_okay=False,
        help="YAML overriding SmootherConfig fields "
             "(min_segment_duration_sec / forbidden_transitions / "
             "viterbi_enabled / lambda_forbidden). Required when "
             "--target-phase = 4 unless defaults are acceptable. "
             "Missing fields fall back to spec §2 defaults. "
             "--no-viterbi overrides viterbi_enabled from this file.",
    ),
    no_viterbi: bool = typer.Option(
        False, "--no-viterbi",
        help="Disable the Phase 4 Viterbi relabel step (spec §3.4). "
             "Overrides viterbi_enabled from --smoother-config.",
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
        try:
            if vlm_model is None:
                raise VLMModelRequired(target_phase=target_phase)
            preflight = resolve_vlm_model(vlm_model, offline=offline)
            vlm_config = VLMConfig(
                model_id=preflight.model_id,
                resolved_checkpoint=preflight.resolved_checkpoint,
                fixture_path=preflight.fixture_path,
                keyframes_per_segment=vlm_keyframes,
                max_retries=vlm_max_retries,
            )
            # Apply optional CLI overrides via dataclasses.replace for typed
            # kwargs (mypy --strict won't accept **dict[str, object] expansion).
            if vlm_device is not None:
                vlm_config = replace(vlm_config, device=vlm_device)
            if vlm_timeout_sec is not None:
                vlm_config = replace(vlm_config, timeout_sec=vlm_timeout_sec)
            if not 0.0 <= vlm_mask_alpha <= 1.0:
                raise VLMConfigInvalid(
                    reason=f"--vlm-mask-alpha must be in [0.0, 1.0], got {vlm_mask_alpha}",
                )
            from mimicanno.config import MaskOverlayConfig
            vlm_config = replace(
                vlm_config,
                mask_overlay=MaskOverlayConfig(
                    enabled=vlm_mask_overlay, alpha=vlm_mask_alpha,
                ),
            )
            if vlm_config.keyframes_per_segment < 1:
                raise VLMConfigInvalid(reason="--vlm-keyframes must be >= 1")
        except MimicAnnoError as e:
            write_error_json(e)
            raise typer.Exit(code=2) from None

    # Phase 3 prerequisites (spec §8 Tier-1 abort guards).
    sam3_checkpoint_resolved: str | None = None
    tracking_config: TrackingConfig | None = None
    if target_phase >= 3:
        try:
            # 1. Verify sam3 backend importable BEFORE any file IO.
            from mimicanno.object_tracker.sam3_runtime import (
                _ensure_transformers_sam3_importable,
            )
            _ensure_transformers_sam3_importable()
            # 2. Verify --sam3-checkpoint provided.
            if sam3_checkpoint is None:
                raise MissingDependencyError(field="--sam3-checkpoint")
            # 3. Resolve checkpoint sha256.
            sam3_checkpoint_resolved = resolve_sam3_checkpoint(sam3_checkpoint)
            # 4. Build TrackingConfig. The path is carried so Task 19's
            # orchestrator can pass it to SAM3Runtime.load(); the sha256
            # (sam3_checkpoint_resolved) goes into ModelConfig for the hash.
            tracking_config = TrackingConfig(
                sam3_checkpoint=str(sam3_checkpoint),
                sam3_offload=sam3_offload,
                track_stride_frames=track_stride_frames,
            )
        except MimicAnnoError as e:
            write_error_json(e)
            raise typer.Exit(code=2) from None

    # Phase 4 prerequisite (spec §5): load + validate --smoother-config.
    smoother_cfg: SmootherConfig | None = None
    if target_phase >= 4:
        try:
            # Need allowed_labels for forbidden-transition validation. Load
            # the labelset just for that — orchestrator will load it again.
            from mimicanno.labelset import default_labels_path, load_label_set
            labels_path_for_validation = labels or Path(
                default_labels_path("manipulation"),
            )
            label_set_for_validation = load_label_set(labels_path_for_validation)
            allowed_label_ids = [lbl.id for lbl in label_set_for_validation.labels]
            if smoother_config is not None:
                smoother_cfg = load_smoother_config_yaml(
                    smoother_config, allowed_labels=allowed_label_ids,
                )
            else:
                smoother_cfg = SmootherConfig()
            if no_viterbi:
                smoother_cfg = replace(smoother_cfg, viterbi_enabled=False)
        except MimicAnnoError as e:
            write_error_json(e)
            raise typer.Exit(code=2) from None

    cfg = AnnotationConfig(
        boundary=boundary,
        target_phase=target_phase,
        model_config=build_model_config(
            target_phase=target_phase,
            vlm=vlm_config,
            tracking=tracking_config,
            sam3_checkpoint_sha256=sam3_checkpoint_resolved,
        ),
        vlm=vlm_config,
        tracking=tracking_config,
        smoother=smoother_cfg,
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
        if cfg.target_phase >= 4:
            annotate_episode_phase4(req)
        elif cfg.target_phase == 3:
            annotate_episode_phase3(req)
        else:
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


@app.command("export")
def export_cmd(
    dataset: Path = typer.Option(..., "--dataset", help="Source LeRobot v3 dataset root."),
    runs_root: Path | None = typer.Option(
        None, "--runs-root",
        help="mimicanno runs/ root. Defaults to $CWD/runs.",
    ),
    target_phase: int = typer.Option(
        ..., "--target-phase",
        help="Which mimicanno pipeline phase to export (1, 2, 3, or 4).",
    ),
    profile: str = typer.Option(
        ..., "--profile",
        help=(
            "Profile name (e.g. 'so101_sarm') or path to a profile YAML "
            "(./my_profile.yaml or absolute path)."
        ),
    ),
    out: Path | None = typer.Option(
        None, "--out",
        help="Output dataset root. Required unless --in-place is set.",
    ),
    config_hash: str | None = typer.Option(
        None, "--config-hash",
        help="Filter to a specific config_hash when an episode has multiple runs.",
    ),
    run: list[str] = typer.Option(
        [], "--run",
        help="Explicit canonical run name(s); overrides target_phase auto-discovery. Repeatable.",
    ),
    episode: list[int] = typer.Option(
        [], "--episode",
        help="Restrict export to specific episode_index(es). Repeatable.",
    ),
    symlink_data: bool = typer.Option(
        False, "--symlink-data",
        help="Symlink videos/, rebuild data/, fresh meta/ (default).",
    ),
    copy_data: bool = typer.Option(
        False, "--copy-data",
        help="Full copy of videos/ instead of symlink.",
    ),
    in_place: bool = typer.Option(
        False, "--in-place",
        help="Mutate <dataset> in-place. Requires --yes-i-mean-it.",
    ),
    yes_i_mean_it: bool = typer.Option(
        False, "--yes-i-mean-it",
        help="Confirm --in-place mutation.",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Replace existing OUT (overrides idempotency short-circuit).",
    ),
    require_reviewed: bool = typer.Option(
        False, "--require-reviewed",
        help="Refuse runs with reviewed=False segments.",
    ),
    allow_degraded: bool = typer.Option(
        False, "--allow-degraded",
        help="Accept manifests with degraded_from_phase != None.",
    ),
    allow_unlabeled: bool = typer.Option(
        False, "--allow-unlabeled",
        help="Accept segments with phase='unlabeled'.",
    ),
    skip_missing: bool = typer.Option(
        False, "--skip-missing",
        help="Warn instead of fail-fast on missing run for an episode.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Plan only; print machine-readable JSON of intended writes; exit 0.",
    ),
) -> None:
    """Export annotated episodes to a SARM-trainable LeRobot v3 dataset."""
    # Validate output-mode mutex (spec §6).
    mode_flags = sum([symlink_data, copy_data, in_place])
    if mode_flags > 1:
        write_error_json(
            MimicAnnoError(
                code=ErrorCode.EXPORT_PROFILE_INVALID,
                message=(
                    "--symlink-data, --copy-data, --in-place are mutually exclusive"
                ),
                context={
                    "symlink_data": symlink_data,
                    "copy_data": copy_data,
                    "in_place": in_place,
                },
            )
        )
        raise typer.Exit(code=2)

    # Default mode is symlink.
    if in_place:
        output_mode = "in_place"
    elif copy_data:
        output_mode = "copy"
    else:
        output_mode = "symlink"

    # --in-place requires --yes-i-mean-it.
    if in_place and not yes_i_mean_it:
        write_error_json(
            MimicAnnoError(
                code=ErrorCode.EXPORT_INPLACE_NO_CONFIRM,
                message=(
                    "--in-place requires --yes-i-mean-it; this mutates the source "
                    "dataset and creates a backup directory inside it"
                ),
                context={"dataset": str(dataset)},
            )
        )
        raise typer.Exit(code=2)

    # OUT is required unless --in-place.
    if not in_place and out is None:
        write_error_json(
            MimicAnnoError(
                code=ErrorCode.EXPORT_OUT_PARENT_MISSING,
                message="--out is required unless --in-place is set",
                context={},
            )
        )
        raise typer.Exit(code=2)

    runs_root_resolved = runs_root if runs_root is not None else Path.cwd() / "runs"
    # In --in-place, bulk_export ignores `out` for path purposes but we still
    # pass dataset for consistency.
    out_resolved: Path = out if out is not None else dataset

    # Resolve profile (catches not-found / invalid).
    try:
        profile_obj = ExportProfile.resolve(profile)
    except MimicAnnoError as e:
        write_error_json(e)
        raise typer.Exit(code=2) from None

    # Capture cli_args for provenance.
    cli_args = sys.argv[1:]

    try:
        result = bulk_export(
            dataset_root=dataset,
            runs_root=runs_root_resolved,
            target_phase=target_phase,
            profile=profile_obj,
            out=out_resolved,
            output_mode=output_mode,  # type: ignore[arg-type]
            config_hash=config_hash,
            explicit_runs=list(run) if run else None,
            episode_filter=list(episode) if episode else None,
            force=force,
            require_reviewed=require_reviewed,
            allow_degraded=allow_degraded,
            allow_unlabeled=allow_unlabeled,
            skip_missing=skip_missing,
            dry_run=dry_run,
            cli_args=cli_args,
        )
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
        raise typer.Exit(code=1) from e

    # bulk_export already emits the dry-run JSON to stdout; nothing to add.
    if dry_run:
        raise typer.Exit(code=0)

    summary = {
        "out": str(result.out_path),
        "episode_count": result.episode_count,
        "manifest_path": str(result.manifest_path),
        "reused": result.reused,
    }
    sys.stdout.write(json.dumps(summary))
    sys.stdout.write("\n")
    sys.stdout.flush()


@app.command("serve")
def serve_cmd(
    runs_root: Path = typer.Option(
        ..., "--runs-root", exists=True, file_okay=False, dir_okay=True,
        help="Directory containing the runs/ tree (with index.json).",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host (default localhost-only)."),
    port: int = typer.Option(8000, "--port", help="Bind port."),
    cors_origin: list[str] | None = typer.Option(
        None, "--cors-origin",
        help="CORS allow-origin (repeatable). Default: empty (CORS disabled).",
    ),
    reload: bool = typer.Option(
        False, "--reload",
        help="Pass uvicorn reload=True (dev only).",
    ),
) -> None:
    """Start the Phase 5 A read-only HTTP server.

    Run ``uv sync --extra server`` first to install fastapi + uvicorn.
    """
    try:
        from mimicanno.server.app import create_app
        import uvicorn
    except ImportError as exc:
        typer.echo(
            f"server extra not installed ({exc}). "
            "Run: uv sync --extra server",
            err=True,
        )
        raise typer.Exit(2)
    origins = cors_origin or []
    # T9: reviewer comes from MIMICANNO_REVIEWER env. Empty/whitespace-only
    # collapses to None so segments edited via this server land with
    # reviewer_id=None rather than reviewer_id="" (matches T6h hash
    # normalisation `(reviewer or "")`).
    reviewer = (os.environ.get("MIMICANNO_REVIEWER") or "").strip() or None
    fastapi_app = create_app(
        runs_root=runs_root, cors_origins=origins, reviewer=reviewer,
    )
    uvicorn.run(fastapi_app, host=host, port=port, reload=reload)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover — invoked via `python -m mimicanno.cli`
    main()
