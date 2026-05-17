"""SAM3Runtime — the ONLY file that imports the ``sam3`` submodule (spec §2.3).

Thin wrapper over the vendored sam3 native API (``Sam3VideoPredictor``).
All other modules interact with this abstraction; they never import ``sam3.*``
directly.

2026-05-04: backend swapped from ``transformers.Sam3*`` to the
``gayagayataiga/sam3`` git submodule's request-style video predictor — see
``docs/superpowers/specs/2026-05-04-sam3-submodule-backend-design.md`` for
rationale + open questions verified by ``scripts/smoke_sam3_bbox_only.py``.

Usage:
    runtime = SAM3Runtime.load(
        checkpoint=Path("sam3/checkpoints/sam3.pt"),
        device="cuda",
        offload_video_to_cpu=True,
    )
    detections = runtime.ground_on_frame(frame_array, "red block")
    for result in runtime.propagate(
        video_path=Path("episode.mp4"),
        prompts_with_initial_bbox=[("red block", bbox)],
        expected_frames={0, 5, 10, 15},
    ):
        ...
    runtime.close()
"""

from __future__ import annotations

import gc
import logging
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from mimicanno.errors import SAM3ExtrasMissing, SAM3InitFailed
from mimicanno.object_tracker.propagator import BBox

_LOG = logging.getLogger(__name__)

# Resolve the bpe asset path eagerly. sam3's editable install breaks
# ``pkg_resources.resource_filename("sam3", ...)`` (returns None for the
# namespace package) so we feed the path explicitly to the model builder.
# Computed relative to this file: <repo>/mimicanno/object_tracker → <repo>/sam3.
_SAM3_BPE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "sam3" / "sam3" / "assets" / "bpe_simple_vocab_16e6.txt.gz"
)

# ---------------------------------------------------------------------------
# FramePropagationResult (production type; fixtures.py re-exports this)
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class FramePropagationResult:
    """Output of SAM3Runtime.propagate() — one frame's detection results.

    frame: the integer frame index
    detections: dict[prompt] -> (BBox, score) | None, where None means
        the prompt was not detected or tracking was lost.
    masks: dict[prompt] -> 2-D bool ndarray | None. Same key set as
        ``detections`` (invariant, enforced in ``__post_init__``). ``None``
        means no mask is available for that prompt at this frame (track
        lost or mask extraction skipped). Mask shape is whatever SAM3
        returned (usually downsampled to keyframe size by the caller).

    BBox coords are normalized [0, 1] per spec §2.4.
    """

    frame: int
    detections: dict[str, tuple[BBox, float] | None]
    masks: dict[str, np.ndarray | None]

    def __post_init__(self) -> None:
        if set(self.detections.keys()) != set(self.masks.keys()):
            raise ValueError(
                "FramePropagationResult invariant violated: "
                f"detections keys {sorted(self.detections.keys())!r} != "
                f"masks keys {sorted(self.masks.keys())!r}"
            )


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


def _ensure_sam3_importable() -> None:
    """Verify that the vendored sam3 submodule is importable.

    Raises:
        SAM3ExtrasMissing: if the editable ``sam3`` install is missing or
            broken (e.g., the submodule wasn't initialized).
    """
    try:
        from sam3.model_builder import build_sam3_video_predictor  # noqa: F401
    except (ImportError, AttributeError) as exc:
        raise SAM3ExtrasMissing() from exc


# Backwards-compat alias kept for callers that still import the old name.
# Removal target: after the SAM3 backend swap branch lands and downstream
# code is migrated.
_ensure_transformers_sam3_importable = _ensure_sam3_importable


# ---------------------------------------------------------------------------
# Private post-processing helpers
# ---------------------------------------------------------------------------


def _extract_bboxes_scores(output: Any) -> list[tuple[BBox, float]]:
    """Convert Sam3ImageSegmentationOutput to (BBox, score) pairs sorted desc.

    Returns BBoxes with top-left x/y + w/h in normalized [0, 1] coords.

    TODO(Task 25): The output is assumed to expose `pred_boxes` (shape (1, N, 4),
    cxcywh, normalized [0, 1]) and `pred_scores` (shape (1, N)). Confirm the
    exact attribute names + normalization against real `Sam3Model` weights and
    update this helper if the API differs (e.g., `logits_per_image`, `boxes`,
    pixel-space outputs).
    """
    import torch

    pred_boxes: Any = output.pred_boxes
    pred_scores: Any = output.pred_scores

    boxes = pred_boxes[0]
    scores = pred_scores[0]

    if isinstance(scores, torch.Tensor):
        scores_np: np.ndarray = scores.detach().cpu().numpy()
    else:
        scores_np = np.asarray(scores, dtype=np.float32)

    if isinstance(boxes, torch.Tensor):
        boxes_np: np.ndarray = boxes.detach().cpu().numpy()
    else:
        boxes_np = np.asarray(boxes, dtype=np.float32)

    results: list[tuple[BBox, float]] = []
    for i in range(int(scores_np.shape[0])):
        cx = float(boxes_np[i, 0])
        cy = float(boxes_np[i, 1])
        # Clamp w/h FIRST so that derived x/y respect the unit square.
        bw = float(np.clip(boxes_np[i, 2], 1e-6, 1.0))
        bh = float(np.clip(boxes_np[i, 3], 1e-6, 1.0))
        x = float(np.clip(cx - bw / 2.0, 0.0, 1.0 - bw))
        y = float(np.clip(cy - bh / 2.0, 0.0, 1.0 - bh))
        score = float(scores_np[i])
        try:
            bbox = BBox(x=x, y=y, w=bw, h=bh)
        except ValueError:
            continue
        results.append((bbox, score))

    results.sort(key=lambda t: t[1], reverse=True)
    return results


# ---------------------------------------------------------------------------
# 2026-05-04 SAM3 backend swap — sam3 native output dict helpers
# (consumed by SAM3Runtime methods that talk to build_sam3_video_predictor)
# ---------------------------------------------------------------------------


def _coerce_outputs_arrays(
    outputs: dict,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Validate + coerce sam3 native ``outputs`` dict into (obj_ids, boxes_xywh, probs).

    sam3's `add_prompt` / `propagate_in_video` emit:

      {
        "out_obj_ids":    ndarray[N]   int64,
        "out_boxes_xywh": ndarray[N,4] float32,  # top-left xywh, normalized [0,1]
        "out_probs":      ndarray[N]   float32,
        "out_binary_masks": ndarray[N,H,W] bool,
        "frame_stats":    dict,
      }

    Verified by `scripts/smoke_sam3_bbox_only.py` (2026-05-04). Empty cases
    surface as shape (0,) / (0,4) — never None.

    Defensive: accepts list-of-list inputs (numpy coerces) so callers and
    tests can pass plain Python literals. A missing required key raises
    ``KeyError`` with a clear message — silent defaults would hide sam3 API
    drift.

    Raises:
        KeyError:   required output key missing.
        ValueError: shapes inconsistent (e.g., len(boxes) != len(obj_ids)).
    """
    for key in ("out_obj_ids", "out_boxes_xywh", "out_probs"):
        if key not in outputs:
            raise KeyError(
                f"sam3 outputs missing required key {key!r}; got "
                f"{sorted(outputs.keys())}"
            )
    obj_ids = np.asarray(outputs["out_obj_ids"]).astype(np.int64, copy=False)
    boxes = np.asarray(outputs["out_boxes_xywh"], dtype=np.float32)
    probs = np.asarray(outputs["out_probs"], dtype=np.float32)
    if boxes.ndim != 2 or boxes.shape[-1] != 4:
        raise ValueError(
            f"out_boxes_xywh must have shape (N, 4); got shape={boxes.shape}"
        )
    n = int(obj_ids.shape[0])
    if boxes.shape[0] != n or probs.shape[0] != n:
        raise ValueError(
            f"sam3 outputs length mismatch: obj_ids={n} "
            f"boxes={boxes.shape[0]} probs={probs.shape[0]}"
        )
    return obj_ids, boxes, probs


def _outputs_to_bbox_score_list(outputs: dict) -> list[tuple[BBox, float]]:
    """Convert one sam3 frame's outputs dict to ``[(BBox, score), ...]``.

    Used for grounding (one-frame text prompt). Out-of-range or degenerate
    BBoxes (x+w > 1.0, w < BBox's lower bound) are silently skipped — sam3
    weights occasionally emit boxes a hair outside [0,1] which BBox's range
    invariant rejects. The skip is preferable to clamping because clamping
    a meaningless detection just hides the issue.

    Returned list is sorted by descending score.

    The input boxes are *top-left xywh, normalized [0,1]* (verified
    2026-05-04 against bedroom.mp4). No cxcywh→xywh conversion is needed,
    unlike the legacy transformers `_extract_bboxes_scores`.
    """
    obj_ids, boxes, probs = _coerce_outputs_arrays(outputs)
    results: list[tuple[BBox, float]] = []
    for i in range(int(obj_ids.shape[0])):
        x = float(boxes[i, 0])
        y = float(boxes[i, 1])
        w = float(boxes[i, 2])
        h = float(boxes[i, 3])
        score = float(probs[i])
        try:
            results.append((BBox(x=x, y=y, w=w, h=h), score))
        except ValueError:
            # Out-of-range or degenerate bbox; skip silently. Logging would
            # spam at every grounding call against multi-instance scenes.
            continue
    results.sort(key=lambda t: t[1], reverse=True)
    return results


def _outputs_to_mask(
    outputs: dict,
    *,
    target_obj_id: int = 0,
    target_size_hw: tuple[int, int] | None = None,
) -> np.ndarray | None:
    """Pick the binary mask for ``target_obj_id`` from one frame's outputs.

    Spec 2026-05-04 §4.4: masks are downsampled to ``target_size_hw`` at
    storage time so the overlay compositor can blit without resampling. If
    ``target_size_hw`` is ``None`` the raw sam3 mask is returned (used in
    unit tests to assert pre-downsample shape).

    Returns ``None`` if the obj_id is missing (track lost, mirroring
    ``_outputs_to_bbox_score``) or if ``out_binary_masks`` is absent
    (sam3 versions without mask emission). Mismatched shapes between
    obj_ids and out_binary_masks raise — that's an API drift bug, not a
    runtime gap.
    """
    obj_ids, _, _ = _coerce_outputs_arrays(outputs)
    n = int(obj_ids.shape[0])
    if n == 0:
        return None
    matches = np.flatnonzero(obj_ids == int(target_obj_id))
    if matches.size == 0:
        return None
    if "out_binary_masks" not in outputs:
        return None
    masks_arr = np.asarray(outputs["out_binary_masks"])
    if masks_arr.ndim != 3:
        raise ValueError(
            f"out_binary_masks must have shape (N,H,W); got {masks_arr.shape}"
        )
    if masks_arr.shape[0] != n:
        raise ValueError(
            f"out_binary_masks length {masks_arr.shape[0]} != obj_ids {n}"
        )
    mask = masks_arr[int(matches[0])].astype(bool, copy=False)
    if target_size_hw is None or mask.shape == target_size_hw:
        return mask
    import cv2  # local import — cv2 is heavy and only needed when downsampling.
    th, tw = target_size_hw
    resized = cv2.resize(
        mask.astype(np.uint8), (tw, th), interpolation=cv2.INTER_NEAREST,
    )
    return resized.astype(bool)


def _outputs_to_bbox_score(
    outputs: dict, *, target_obj_id: int = 0,
) -> tuple[BBox, float] | None:
    """Pick the entry for ``target_obj_id`` from one frame's outputs.

    Used for propagation (one tracked object per session). When sam3 loses
    the track, the obj_id silently disappears from `out_obj_ids` (verified
    2026-05-04) — we map that to ``None`` so callers can treat lost frames
    as gaps without inspecting array shapes.

    A bbox that fails BBox's range check (rare, but happens on edge cases
    near the frame boundary) is also returned as ``None``: a bogus bbox
    is no better than a lost track for the propagator's gap-detection.
    """
    obj_ids, boxes, probs = _coerce_outputs_arrays(outputs)
    n = int(obj_ids.shape[0])
    if n == 0:
        return None
    target = int(target_obj_id)
    matches = np.flatnonzero(obj_ids == target)
    if matches.size == 0:
        return None
    i = int(matches[0])
    x = float(boxes[i, 0])
    y = float(boxes[i, 1])
    w = float(boxes[i, 2])
    h = float(boxes[i, 3])
    try:
        return BBox(x=x, y=y, w=w, h=h), float(probs[i])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# SAM3Runtime
# ---------------------------------------------------------------------------


class SAM3Runtime:
    """Thin wrapper over the vendored sam3 ``Sam3VideoPredictor`` (spec §2.3).

    Lifecycle: create via ``load()``; call ``ground_on_frame()`` and
    ``propagate()``; call ``close()`` when done (idempotent).

    Internally we hold a single sam3 video predictor and re-use it across
    grounding (1-frame text-prompt sessions) and propagation (1-prompt-per-
    session round-robin). Sessions are tracked in ``_open_sessions`` so that
    ``close()`` can guarantee teardown even if a generator is abandoned.
    """

    def __init__(
        self,
        *,
        _predictor: Any,
        _device: str,
        _offload_video: bool,
    ) -> None:
        """Internal — use SAM3Runtime.load() instead."""
        self._predictor = _predictor
        self._device = _device
        self._offload_video = _offload_video
        self._open_sessions: list[str] = []
        self._closed = False

    @classmethod
    def load(
        cls,
        *,
        checkpoint: str | Path,
        device: str = "cuda",
        offload_video_to_cpu: bool = True,
    ) -> SAM3Runtime:
        """Load SAM3 from a local checkpoint file.

        Args:
            checkpoint: filesystem path to a SAM3 weights file (e.g.
                ``Path("sam3/checkpoints/sam3.pt")``). Strings are accepted
                for backwards compat with the prior transformers-id signature
                but are passed through verbatim — there is no HF download
                fallback any more.
            device: torch device string (e.g., "cuda", "cpu"). The sam3
                predictor itself is hard-wired to CUDA in
                ``Sam3VideoPredictorMultiGPU``; this argument primarily
                selects which CUDA index to bind via ``torch.cuda.set_device``.
            offload_video_to_cpu: if ``True`` (default), each session
                materializes the video tensor on the CPU and streams to GPU
                per-frame. With per-prompt-per-session round-robin (see
                :py:meth:`propagate`), this matters: N tracked objects = N
                video tensors, so without offload long episodes can OOM.

        Returns:
            Initialized SAM3Runtime.

        Raises:
            SAM3ExtrasMissing: if the sam3 submodule isn't importable.
            SAM3InitFailed: if ``build_sam3_video_predictor`` raises
                (missing weights, CUDA OOM, bad bpe path, etc.).
        """
        _ensure_sam3_importable()

        # Import here so any late import error surfaces via SAM3ExtrasMissing
        # above (build_sam3_video_predictor's own imports can fail at runtime
        # in addition to the top-level sam3 module).
        from sam3.model_builder import build_sam3_video_predictor

        checkpoint_str = str(checkpoint)
        if not _SAM3_BPE_PATH.exists():
            raise SAM3InitFailed(
                underlying=(
                    f"sam3 bpe asset missing at {_SAM3_BPE_PATH!s}; did you "
                    "run `git submodule update --init sam3`?"
                ),
            )

        try:
            import torch

            # Bind this process to the requested CUDA device before model
            # construction — Sam3VideoPredictorMultiGPU caches the device
            # at __init__ time. ``torch.cuda.set_device`` requires an
            # explicit index (``"cuda:0"`` or ``0``); the bare string
            # ``"cuda"`` is rejected, so skip the call for the no-index
            # variant (current_device stays at the default).
            if (
                device.startswith("cuda")
                and ":" in device
                and torch.cuda.is_available()
            ):
                torch.cuda.set_device(device)
            predictor = build_sam3_video_predictor(
                checkpoint_path=checkpoint_str,
                bpe_path=str(_SAM3_BPE_PATH),
            )
        except Exception as exc:
            raise SAM3InitFailed(underlying=repr(exc)) from exc

        return cls(
            _predictor=predictor,
            _device=device,
            _offload_video=offload_video_to_cpu,
        )

    # ------------------------------------------------------------------
    # Grounding
    # ------------------------------------------------------------------

    def ground_on_frame(
        self,
        frame: np.ndarray,
        prompt: str,
        *,
        frame_index: int | None = None,  # NEW: accepted but unused (real SAM3 sends frame bytes; see fixtures.py for frame-keyed lookup)
    ) -> list[tuple[BBox, float]]:
        """Run text-prompted grounding on a single frame.

        Implementation: write the frame to a NamedTemporaryFile JPEG and
        ``start_session(resource_path=<that file>)``. sam3's resource loader
        accepts a single image path directly (verified 2026-05-04 smoke),
        avoiding the temp-dir-with-stray-files problem.

        Args:
            frame: HxWxC uint8 numpy array (RGB).
            prompt: text prompt string (e.g., "red block").
            frame_index: video frame index (accepted but unused — real SAM3
                always anchors at frame_idx=0 within its single-frame session).

        Returns:
            List of (BBox, score) sorted by descending score. May be empty
            if the model detects nothing.
        """
        if self._closed:
            raise RuntimeError("SAM3Runtime is closed")

        from PIL import Image

        # delete=False so we keep the file alive across handle_request calls;
        # the finally block unlinks it.
        tf = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tf.close()
        tmp_path = Path(tf.name)
        sid: str | None = None
        try:
            Image.fromarray(frame).save(tmp_path, quality=95)

            resp = self._predictor.handle_request({
                "type": "start_session",
                "resource_path": str(tmp_path),
            })
            sid = resp["session_id"]
            self._open_sessions.append(sid)

            add = self._predictor.handle_request({
                "type": "add_prompt",
                "session_id": sid,
                "frame_index": 0,
                "text": prompt,
                "rel_coordinates": True,
            })
            return _outputs_to_bbox_score_list(add["outputs"])
        finally:
            if sid is not None:
                self._close_session(sid)
            tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Propagation
    # ------------------------------------------------------------------

    def propagate(
        self,
        *,
        video_path: Path,
        prompts_with_initial_bbox: list[tuple[str, BBox]],
        expected_frames: set[int],
        mask_size_hw: tuple[int, int] | None = None,
    ) -> Iterator[FramePropagationResult]:
        """Propagate tracked objects across a video.

        One sam3 session per prompt — multiple visual bbox prompts in a
        single session would trip sam3's "visual prompt expects exactly one
        box" assertion (verified by scripts/smoke_sam3_bbox_only.py and
        documented in spec §4.2). Per-frame outputs from the N parallel
        streams are merged in lock-step on ``frame_index`` and emitted as a
        single ``FramePropagationResult`` per expected frame.

        Args:
            video_path: filesystem path to the source video (or JPEG dir).
                sam3 owns the frame loader.
            prompts_with_initial_bbox: ``[(prompt, initial_bbox), ...]``.
                The initial bbox seeds tracking at ``frame_index=0``.
            expected_frames: integer frame indices the caller wants to
                consume. Frames produced by sam3 outside this set are
                silently dropped, so the runtime is responsible for
                materialising every frame sam3 emits but the propagator
                receives only the strided subset.

        Yields:
            ``FramePropagationResult`` for each frame in
            ``sorted(expected_frames)`` that was reached. ``detections[prompt]``
            is ``None`` if the tracker lost that prompt for that frame.
        """
        if self._closed:
            raise RuntimeError("SAM3Runtime is closed")
        if not prompts_with_initial_bbox:
            return  # nothing to track

        # Open all sessions up-front so any add_prompt error fails loudly
        # before we start consuming the streams.
        prompt_streams: list[tuple[str, str, Iterator[dict]]] = []
        try:
            for prompt, bbox in prompts_with_initial_bbox:
                resp = self._predictor.handle_request({
                    "type": "start_session",
                    "resource_path": str(video_path),
                    "offload_video_to_cpu": self._offload_video,
                })
                sid = resp["session_id"]
                self._open_sessions.append(sid)

                # Pass BOTH text (from the entity prompt) AND the bbox seed.
                # sam3's bbox-only visual prompt mode tracks poorly across
                # frames on real SO101 data (verified in
                # docs/superpowers/notes/2026-05-04-sam3-smoke-results.md);
                # adding the text label to the same prompt lets sam3 ground
                # the tracker on a semantic concept while still getting the
                # spatial seed from grounding.
                self._predictor.handle_request({
                    "type": "add_prompt",
                    "session_id": sid,
                    "frame_index": 0,
                    "obj_id": 0,
                    "text": prompt,
                    "bounding_boxes": [
                        [bbox.x, bbox.y, bbox.w, bbox.h],
                    ],
                    "bounding_box_labels": [1],
                    "rel_coordinates": True,
                })
                stream = iter(self._predictor.handle_stream_request({
                    "type": "propagate_in_video",
                    "session_id": sid,
                    "propagation_direction": "forward",
                }))
                prompt_streams.append((prompt, sid, stream))

            yield from self._merge_streams(
                prompt_streams, expected_frames, mask_size_hw,
            )
        finally:
            # Close any still-open sessions for these prompts. close() at the
            # Runtime level will mop up stragglers if the generator was
            # abandoned mid-iteration.
            for _, sid, _ in prompt_streams:
                self._close_session(sid)

    def _merge_streams(
        self,
        prompt_streams: list[tuple[str, str, Iterator[dict]]],
        expected_frames: set[int],
        mask_size_hw: tuple[int, int] | None = None,
    ) -> Iterator[FramePropagationResult]:
        """Round-robin merge: every active stream yields the same frame_idx
        in the same order (verified Q6 in 2026-05-04 smoke). We pull one
        item per stream, take the min frame_idx as the current round's
        anchor, and assemble the per-prompt detections dict.

        If a stream ends early (sam3 lost track + truncated propagation),
        its prompt's detections become ``None`` for all subsequent frames.
        Frames outside ``expected_frames`` are skipped from the yield but
        still consumed from the streams to keep alignment.
        """
        # buffer[i] = next item from stream i, or None if exhausted
        buffer: list[dict | None] = [next(s, None) for _, _, s in prompt_streams]

        while any(item is not None for item in buffer):
            current_frame = min(
                item["frame_index"] for item in buffer if item is not None
            )

            detections: dict[str, tuple[BBox, float] | None] = {}
            masks: dict[str, np.ndarray | None] = {}
            for i, (prompt, _sid, stream) in enumerate(prompt_streams):
                item = buffer[i]
                if item is None or item["frame_index"] != current_frame:
                    detections[prompt] = None
                    masks[prompt] = None
                    continue
                detections[prompt] = _outputs_to_bbox_score(
                    item["outputs"], target_obj_id=0,
                )
                # Mask extraction is opt-in: when mask_size_hw is None we
                # leave masks as None placeholders to keep the no-overlay
                # path bit-identical to pre-Task 5 behaviour.
                if mask_size_hw is not None:
                    masks[prompt] = _outputs_to_mask(
                        item["outputs"],
                        target_obj_id=0,
                        target_size_hw=mask_size_hw,
                    )
                else:
                    masks[prompt] = None
                buffer[i] = next(stream, None)

            if current_frame in expected_frames:
                yield FramePropagationResult(
                    frame=current_frame, detections=detections, masks=masks,
                )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _close_session(self, sid: str) -> None:
        """Close one session, swallowing errors. ``close_session`` is
        idempotent on the sam3 side (verified E4 smoke) but we still guard
        against double-removal from ``_open_sessions``.
        """
        if sid not in self._open_sessions:
            return
        try:
            self._predictor.handle_request({
                "type": "close_session",
                "session_id": sid,
                "run_gc_collect": False,  # batched at Runtime.close()
            })
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("close_session(%s) raised: %r", sid, exc)
        finally:
            try:
                self._open_sessions.remove(sid)
            except ValueError:
                pass

    def _close_all_sessions(self) -> None:
        """Close every open session, leave the predictor + closed flag intact.

        バッチ実行で同一ランタイムを複数エピソードに渡って使い回す経路
        (``AnnotateRequest.preloaded_sam3_runtime``) で呼ばれる。
        セッション解放だけ行い、``_predictor`` と ``_closed`` には触らない
        ので、次のエピソードでそのまま使い回せる。

        さらに ``gc.collect()`` + ``torch.cuda.empty_cache()`` をここで
        呼ぶ。これは review C4 対応: PyTorch の CUDA caching allocator が
        セッション解放後にも論理的に確保したままにする領域を、エピソード
        間でリリースして VRAM 累積を抑えるため。``close()`` 本体と同じ
        最終処理 (per-session ではなく per-episode) を踏襲しているので、
        他 GPU 上のモデル (例: VLM) を churn する心配は無い。
        """
        for sid in list(self._open_sessions):
            self._close_session(sid)
        try:
            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("SAM3Runtime._close_all_sessions cleanup failed: %r", exc)

    def close(self) -> None:
        """Release runtime resources. Idempotent — safe to call repeatedly.

        Closes every still-open session via ``_close_all_sessions()``
        (which also runs gc.collect + torch.cuda.empty_cache), then drops
        the predictor reference. spec §3.3 + spec review #14.
        """
        if self._closed:
            return
        self._closed = True

        self._close_all_sessions()  # gc.collect + empty_cache はこの中

        # Drop the predictor reference last; sam3's predictor doesn't expose
        # an explicit shutdown for the single-GPU path, so GC owns the rest.
        self._predictor = None
