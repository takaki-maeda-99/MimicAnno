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
from typing import TYPE_CHECKING, Any

import numpy as np

from mimicanno.errors import SAM3ExtrasMissing, SAM3InitFailed
from mimicanno.object_tracker.propagator import BBox

if TYPE_CHECKING:
    pass


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


def _extract_bboxes_scores(
    output: Any,
    image_h: int,
    image_w: int,
) -> list[tuple[BBox, float]]:
    """Convert Sam3ImageSegmentationOutput to a list of (BBox, score) pairs.

    Assumes output has:
      - output.pred_boxes: Tensor of shape (1, N, 4) in cxcywh format, values
        in [0, 1] (normalized by image dimensions).
      - output.pred_scores (or logits_per_image): Tensor of shape (1, N).

    The resulting BBox uses top-left x/y + w/h in [0, 1] (spec §2.4).

    Sorted by descending score.

    TODO(Task 25): Confirm the exact field names on Sam3ImageSegmentationOutput
    against real weights.  The HF transformers 5.5 docs list `pred_boxes` and
    `pred_scores`; if the real model uses different field names (e.g.,
    `logits_per_image`, `boxes`) update this helper and remove this marker.
    """
    import torch

    # pred_boxes: (1, N, 4) cxcywh in [0, 1]
    # TODO(Task 25): verify field name `pred_boxes` against real Sam3Model output
    pred_boxes: Any = output.pred_boxes  # shape (1, N, 4)
    # TODO(Task 25): verify field name `pred_scores` against real Sam3Model output
    pred_scores: Any = output.pred_scores  # shape (1, N)

    boxes = pred_boxes[0]   # (N, 4)
    scores = pred_scores[0]  # (N,)

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
        cx, cy, bw, bh = float(boxes_np[i, 0]), float(boxes_np[i, 1]), float(boxes_np[i, 2]), float(boxes_np[i, 3])
        x = cx - bw / 2.0
        y = cy - bh / 2.0
        # Clamp to valid unit-square
        x = max(0.0, min(x, 1.0 - bw))
        y = max(0.0, min(y, 1.0 - bh))
        bw = max(1e-6, min(bw, 1.0))
        bh = max(1e-6, min(bh, 1.0))
        score = float(scores_np[i])
        try:
            bbox = BBox(x=x, y=y, w=bw, h=bh)
        except ValueError:
            continue  # skip degenerate boxes
        results.append((bbox, score))

    results.sort(key=lambda t: t[1], reverse=True)
    return results


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
        checkpoint: str = "facebook/sam3",
        device: str = "cuda",
    ) -> SAM3Runtime:
        """Load SAM3 models from a HF checkpoint or local path.

        Args:
            checkpoint: HF model id or local directory (e.g., "facebook/sam3").
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

        try:
            processor = Sam3Processor.from_pretrained(checkpoint)
            model = Sam3Model.from_pretrained(checkpoint)
            model = model.to(device)
            model.eval()

            tracker_model = Sam3TrackerVideoModel.from_pretrained(checkpoint)
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

        TODO(Task 25): Confirm the Sam3Model.forward() call signature and that
        `Sam3Processor` accepts `text=[prompt]` + `images=[pil_image]` inputs.
        Also confirm the output class is Sam3ImageSegmentationOutput (or
        equivalent) and that post-processing via _extract_bboxes_scores is
        correct. Update if the actual API differs.
        """
        from PIL import Image

        pil_image = Image.fromarray(frame)
        h, w = frame.shape[:2]

        # TODO(Task 25): confirm processor input format (text vs. input_ids,
        # images vs. pixel_values) against real Sam3Processor API.
        inputs = self._processor(
            text=[prompt],
            images=[pil_image],
            return_tensors="pt",
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}

        # TODO(Task 25): confirm Sam3Model.forward() kwarg names match inputs
        # produced by Sam3Processor (no extra adapter needed).
        output = self._model(**inputs)

        return _extract_bboxes_scores(output, image_h=h, image_w=w)

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

        TODO(Task 25): Confirm Sam3TrackerVideoInferenceSession instantiation
        API: constructor args, how to register initial prompts + bboxes, and
        the per-frame inference call signature. The HF transformers docs for
        Sam3TrackerVideoInferenceSession may use a context-manager or an
        explicit add_new_points_or_box() style API (similar to SAM 2). Update
        this method once verified against real weights.
        """
        from PIL import Image

        # TODO(Task 25): confirm Sam3TrackerVideoInferenceSession constructor
        # and initialization API.  The implementation below mirrors the
        # Sam2VideoPredictor pattern; adjust if the real API differs.
        session = self._tracker_model.get_inference_session()

        # Register initial bboxes per prompt.
        # TODO(Task 25): confirm the method name and kwarg names for adding
        # initial object prompts (box coordinates in xyxy or xywh? normalized
        # or pixel? what dtype does the session expect?).
        for obj_idx, (_prompt, bbox) in enumerate(prompts_with_initial_bbox):
            # Convert normalized BBox to xyxy format (normalized [0,1]).
            # TODO(Task 25): confirm whether session expects normalized [0,1]
            # or pixel coords, and xyxy vs xywh.
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

            # TODO(Task 25): confirm per-frame propagation API on
            # Sam3TrackerVideoInferenceSession (method name, arg names, and
            # output format — expected to return per-object masks/boxes/scores).
            frame_result = session.propagate_in_video(
                frame=pil_frame,
                frame_idx=frame_idx,
            )

            detections: dict[str, tuple[BBox, float] | None] = {}
            for obj_idx, prompt in enumerate(prompts_list):
                # TODO(Task 25): confirm how per-object detections are accessed
                # from frame_result (e.g., frame_result[obj_idx] or
                # frame_result.boxes[obj_idx] / frame_result.scores[obj_idx]).
                obj_result = frame_result.get(obj_idx)
                if obj_result is None:
                    detections[prompt] = None
                    continue

                # TODO(Task 25): confirm field names for box + score in
                # per-object result (box in normalized [0,1] xyxy? xywh?).
                box = obj_result.get("box")
                score = obj_result.get("score")
                if box is None or score is None:
                    detections[prompt] = None
                    continue

                # Convert xyxy normalized -> BBox (xywh normalized)
                x0, y0, x1, y1 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
                bw = max(1e-6, x1 - x0)
                bh = max(1e-6, y1 - y0)
                try:
                    detected_bbox = BBox(x=x0, y=y0, w=bw, h=bh)
                    detections[prompt] = (detected_bbox, float(score))
                except ValueError:
                    detections[prompt] = None

            yield FramePropagationResult(frame=frame_idx, detections=detections)

        # TODO(Task 25): confirm whether Sam3TrackerVideoInferenceSession
        # needs explicit cleanup (e.g., session.close() or context manager exit).

    def close(self) -> None:
        """Release model resources. Idempotent — safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        # Release references so that Python/CUDA can free memory.
        # TODO(Task 25): if transformers provides an explicit model.release()
        # or similar method, call it here.
        del self._model
        del self._processor
        del self._tracker_model
        # Avoid AttributeError on subsequent close() calls by resetting to None.
        self._model = None
        self._processor = None
        self._tracker_model = None
