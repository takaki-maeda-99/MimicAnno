"""SAM3Runtime — the ONLY file that imports transformers.Sam3* (spec §2.3).

Thin wrapper over the HF transformers Sam3Model / Sam3TrackerVideoModel backend.
All other modules interact with this abstraction; they never import transformers
Sam3* classes directly.

Usage:
    runtime = SAM3Runtime.load(checkpoint="facebook/sam3", device="cuda")
    detections = runtime.ground_on_frame(frame_array, "red block")
    for result in runtime.propagate(frames=..., prompts_with_initial_bbox=..., stride=1):
        ...
    runtime.close()
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from mimicanno.errors import SAM3ExtrasMissing, SAM3InitFailed
from mimicanno.object_tracker.propagator import BBox

# ---------------------------------------------------------------------------
# FramePropagationResult (production type; fixtures.py re-exports this)
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class FramePropagationResult:
    """Output of SAM3Runtime.propagate() — one frame's detection results.

    frame: the integer frame index
    detections: dict[prompt] -> (BBox, score) | None, where None means
        the prompt was not detected or tracking was lost.

    BBox coords are normalized [0, 1] per spec §2.4.
    """

    frame: int
    detections: dict[str, tuple[BBox, float] | None]


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


def _ensure_transformers_sam3_importable() -> None:
    """Verify that the transformers SAM3 classes are importable.

    Raises:
        SAM3ExtrasMissing: if transformers<5.5 or the Sam3* symbols are missing.
    """
    try:
        from transformers import (  # noqa: F401
            Sam3Model,
            Sam3Processor,
            Sam3TrackerVideoInferenceSession,
            Sam3TrackerVideoModel,
        )
    except (ImportError, AttributeError) as exc:
        raise SAM3ExtrasMissing() from exc


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
    """Thin wrapper over transformers.Sam3* (spec §2.3).

    Lifecycle: create via load(); call ground_on_frame() and propagate();
    call close() when done (idempotent).
    """

    def __init__(
        self,
        _model: Any,
        _processor: Any,
        _tracker_model: Any,
        _device: str,
    ) -> None:
        """Internal — use SAM3Runtime.load() instead."""
        self._model = _model
        self._processor = _processor
        self._tracker_model = _tracker_model
        self._device = _device
        self._closed = False

    @classmethod
    def load(
        cls,
        *,
        checkpoint: str | Path = "facebook/sam3",
        device: str = "cuda",
    ) -> SAM3Runtime:
        """Load SAM3 models from a HF checkpoint or local path.

        Args:
            checkpoint: HF model id or local directory (e.g., "facebook/sam3"
                or `Path("/weights/sam3")`). Spec §2.3 declares `Path`; HF
                `from_pretrained` accepts both, so we normalize via `str()`.
            device: torch device string (e.g., "cuda", "cpu").

        Returns:
            Initialized SAM3Runtime.

        Raises:
            SAM3ExtrasMissing: if transformers Sam3* classes are not available.
            SAM3InitFailed: if from_pretrained raises (OOM, bad weights, etc.).
        """
        _ensure_transformers_sam3_importable()

        # Import here so that import errors surface as SAM3ExtrasMissing above.
        from transformers import (
            Sam3Model,
            Sam3Processor,
            Sam3TrackerVideoModel,
        )

        checkpoint_str = str(checkpoint)
        try:
            processor = Sam3Processor.from_pretrained(checkpoint_str)
            model = Sam3Model.from_pretrained(checkpoint_str)
            model = model.to(device)
            model.eval()

            tracker_model = Sam3TrackerVideoModel.from_pretrained(checkpoint_str)
            tracker_model = tracker_model.to(device)
            tracker_model.eval()
        except Exception as exc:
            raise SAM3InitFailed(underlying=repr(exc)) from exc

        return cls(
            _model=model,
            _processor=processor,
            _tracker_model=tracker_model,
            _device=device,
        )

    def ground_on_frame(
        self,
        frame: np.ndarray,
        prompt: str,
    ) -> list[tuple[BBox, float]]:
        """Run text-prompted grounding on a single frame.

        Args:
            frame: HxWxC uint8 numpy array (RGB).
            prompt: text prompt string (e.g., "red block").

        Returns:
            List of (BBox, score) sorted by descending score. May be empty if
            the model detects nothing.

        TODO(Task 25): Confirm against real `facebook/sam3` weights that (a)
        `Sam3Processor.__call__(text=[prompt], images=[pil_image], return_tensors="pt")`
        produces the kwargs expected by `Sam3Model.forward(**inputs)`, and
        (b) the resulting `Sam3ImageSegmentationOutput` is the input shape
        `_extract_bboxes_scores` consumes. Update both call sites if the
        actual API differs.
        """
        from PIL import Image

        pil_image = Image.fromarray(frame)

        inputs = self._processor(
            text=[prompt],
            images=[pil_image],
            return_tensors="pt",
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}

        output = self._model(**inputs)

        return _extract_bboxes_scores(output)

    def propagate(
        self,
        *,
        frames: Iterator[tuple[int, np.ndarray]],
        prompts_with_initial_bbox: list[tuple[str, BBox]],
        stride: int,
    ) -> Iterator[FramePropagationResult]:
        """Propagate tracked objects across a sequence of frames.

        Args:
            frames: Iterator of (frame_idx, frame_array) tuples where
                frame_array is HxWxC uint8 numpy (RGB). Frames are yielded
                in ascending frame-index order by the caller (Propagator).
            prompts_with_initial_bbox: list of (prompt, BBox) pairs that
                define which objects to track and their initial positions.
            stride: tracking stride hint (informational; frames are pre-strided
                by the caller — this runtime passes them through one by one).

        Yields:
            FramePropagationResult for each frame. detections[prompt] is None
            if the tracker lost the object for that frame.

        TODO(Task 25): Confirm three things against real `Sam3TrackerVideoModel`
        weights, then remove this marker:
        (a) **Session creation:** `tracker_model.get_inference_session()` is
            assumed; the real API may use a constructor (`Sam3TrackerVideoInferenceSession(model)`)
            or context manager.
        (b) **Initial prompt registration:** `session.add_new_points_or_box(
            obj_id, box, frame_idx)` is assumed (mirrors SAM 2). Confirm box
            format (xyxy vs xywh) and coord space (normalized [0, 1] vs pixel).
        (c) **Per-frame call + output shape:** `session.propagate_in_video(frame,
            frame_idx)` is assumed to return a dict keyed by `obj_id` with
            `{"box": [...], "score": float}`. Confirm method name, arg names,
            and per-object result shape — including whether the session needs
            explicit cleanup at the end.
        """
        from PIL import Image

        session = self._tracker_model.get_inference_session()

        for obj_idx, (_prompt, bbox) in enumerate(prompts_with_initial_bbox):
            box_xyxy = [
                bbox.x,
                bbox.y,
                bbox.x + bbox.w,
                bbox.y + bbox.h,
            ]
            session.add_new_points_or_box(
                obj_id=obj_idx,
                box=box_xyxy,
                frame_idx=0,
            )

        prompts_list = [p for p, _ in prompts_with_initial_bbox]

        for frame_idx, frame_array in frames:
            pil_frame = Image.fromarray(frame_array)

            frame_result = session.propagate_in_video(
                frame=pil_frame,
                frame_idx=frame_idx,
            )

            detections: dict[str, tuple[BBox, float] | None] = {}
            for obj_idx, prompt in enumerate(prompts_list):
                obj_result = frame_result.get(obj_idx)
                if obj_result is None:
                    detections[prompt] = None
                    continue

                box = obj_result.get("box")
                score = obj_result.get("score")
                if box is None or score is None:
                    detections[prompt] = None
                    continue

                x0, y0, x1, y1 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
                bw = max(1e-6, x1 - x0)
                bh = max(1e-6, y1 - y0)
                try:
                    detected_bbox = BBox(x=x0, y=y0, w=bw, h=bh)
                    detections[prompt] = (detected_bbox, float(score))
                except ValueError:
                    detections[prompt] = None

            yield FramePropagationResult(frame=frame_idx, detections=detections)

    def close(self) -> None:
        """Release model resources. Idempotent — safe to call multiple times.

        TODO(Task 25): If `Sam3Model` / `Sam3TrackerVideoModel` expose an
        explicit `release()` / `cpu()` / `to_empty()` method to free CUDA
        memory deterministically, call it here in addition to dropping
        references.
        """
        if self._closed:
            return
        self._closed = True
        self._model = None
        self._processor = None
        self._tracker_model = None
