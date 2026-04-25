# MimicAno — Robot Episode Subtask Annotator

## 1. Purpose

Offline subtask annotation pipeline for robot imitation learning episodes. Takes recorded episodes (video + robot state + action), automatically segments them into robot-executable subtask phases, and provides a human review UI for correction.

Designed as an independent Python package that can be used standalone (CLI / API) or embedded into MimicRec.

## 2. Core design principles

1. **VLM は意味付けに使う。境界はロボット状態で出す。**
2. **境界検出とラベリングを分離する。**
3. **時系列制約で平滑化する。**
4. **人間修正を前提とする。完全自動ではない。**
5. **サブタスクラベルは自由記述させない。許可ラベルリストを強制する。**
6. **重い処理（SAM3, VLM）は必ずサンプリングを落とす。**

## 3. Pipeline

```
Episode (video + robot state + action + task name)
    │
    ├─ Step 1: Signal-based boundary detection
    │     ├─ gripper open/close transitions
    │     ├─ EEF velocity valleys (speed drops near zero)
    │     ├─ EEF acceleration peaks (sudden direction changes)
    │     └─ output: candidate boundary timestamps + types
    │
    ├─ Step 2: SAM3 object tracking (sampled)
    │     ├─ Use task name to generate text prompts
    │     │   e.g., task="pick red block" → prompts: "red block", "gripper", "target area"
    │     ├─ Run SAM3 on sampled frames (every Nth frame, configurable)
    │     ├─ Interpolate masks/positions for skipped frames
    │     ├─ Compute: gripper-object distance, object velocity, contact likelihood
    │     └─ Refine boundaries with object-state signals
    │
    ├─ Step 3: Clip segmentation + feature extraction
    │     ├─ Split episode at boundaries → clips
    │     ├─ Per clip: keyframe image, robot state summary, object state summary
    │     └─ Context: previous/next clip info
    │
    ├─ Step 4: VLM structured labeling (Gemma 4)
    │     ├─ Per clip: keyframe + summaries → allowed label + evidence + confidence
    │     ├─ Allowed labels configurable per task type
    │     ├─ JSON-only output, no free-form text
    │     └─ Batched: sample 1-2 frames per clip, not all frames
    │
    ├─ Step 5: Temporal smoothing
    │     ├─ min_duration filter (merge segments < threshold)
    │     ├─ Forbidden transition matrix (e.g., grasp before approach)
    │     ├─ Short identical-label merge
    │     └─ Optional Viterbi / HMM decoding
    │
    └─ Step 6: Human review UI
          ├─ Video player synced with timeline
          ├─ Subtask color bands on timeline
          ├─ Robot state waveforms (gripper, EEF velocity)
          ├─ Object tracks overlay (from SAM3)
          ├─ Confidence heatmap per segment
          ├─ Click-drag to adjust boundaries
          ├─ Dropdown to relabel segments
          ├─ "Review low-confidence only" mode
          └─ Export corrected annotations
```

## 4. Subtask schema

```python
@dataclass
class SubtaskSegment:
    phase: str            # e.g., "grasp_object"
    verb: str             # e.g., "grasp"
    object: str | None    # e.g., "red_block"
    target: str | None    # e.g., "bin_A"
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    evidence: str         # why this label was chosen
    confidence: float     # 0.0 - 1.0
    boundary_source: str  # e.g., "gripper_transition + eef_velocity_valley"
```

## 5. Default allowed labels

Configurable per task type. Default set for manipulation:

```
idle
approach_object
align_gripper
grasp_object
lift_object
move_to_target
align_to_target
place_object
release_object
retreat
failure_recovery
```

## 6. SAM3 integration

- **Prompt generation**: Task name → Gemma 4 extracts object/target names → SAM3 text prompts
  - e.g., task="pick the red block and place in bin" → ["red block", "bin", "gripper/end-effector"]
- **Sampling**: SAM3 runs on every Nth frame (default N=10, ~3fps for 30fps video)
  - Masks interpolated for intermediate frames (linear bbox interpolation)
  - Configurable via `sam3_sample_rate`
- **Output per object per frame**: bbox, mask, centroid position
- **Derived signals**: gripper-object distance, object velocity, contact detection

## 7. VLM labeling strategy

Per clip (not per frame):
```json
{
  "clip_id": 3,
  "start_time": 3.2,
  "end_time": 4.8,
  "keyframe_description": "gripper closing around red block",
  "robot_state": "EEF at (0.3, 0.1, 0.15), gripper 0.8→0.1, velocity near zero",
  "object_state": "red_block distance to gripper: 2cm, stationary→moving at 4.1s",
  "previous_label": "approach_object",
  "allowed_labels": ["grasp_object", "align_gripper", "failure_recovery"],
  "task_name": "pick red block"
}
→ VLM returns:
{
  "label": "grasp_object",
  "verb": "grasp",
  "object": "red_block",
  "evidence": "gripper closes while near red_block, object starts moving",
  "confidence": 0.85
}
```

## 8. Temporal smoothing

```python
# Configurable constraints
min_segment_duration_sec: float = 0.3
forbidden_transitions: list[tuple[str, str]] = [
    ("grasp_object", "approach_object"),  # can't go back
    ("release_object", "grasp_object"),   # must approach again
    ("lift_object", "idle"),              # doesn't make sense
]
merge_threshold_sec: float = 0.2  # merge segments shorter than this
```

## 9. Package structure

```
MimicAno/
  sam3/                    # SAM3 (existing clone)
  mimicanno/
    __init__.py
    pipeline.py            # orchestrate full pipeline
    boundaries.py          # Step 1: signal-based boundary detection
    object_tracker.py      # Step 2: SAM3 wrapper with sampling
    clip_features.py       # Step 3: clip segmentation + feature extraction
    vlm_labeler.py         # Step 4: Gemma 4 structured labeling
    smoother.py            # Step 5: temporal smoothing
    schema.py              # SubtaskSegment, AnnotationConfig, AnnotationResult
    config.py              # default labels, thresholds, model settings
    io.py                  # read LeRobot episodes, write annotations
    api.py                 # FastAPI routes (standalone server)
    cli.py                 # CLI entry point
  frontend/                # Review UI (React, embeddable)
    src/
      AnnotationTimeline.tsx
      WaveformView.tsx
      ObjectTrackOverlay.tsx
      SegmentEditor.tsx
  pyproject.toml
  README.md
```

## 10. MimicRec integration

```python
# In MimicRec's annotator, replace current simple VLM call:
from mimicanno import annotate_episode

result = annotate_episode(
    video_path="datasets/pick/videos/.../episode_000.mp4",
    parquet_path="datasets/pick/data/.../episode_000.parquet",
    task_name="pick red block",
    config=AnnotationConfig(
        allowed_labels=DEFAULT_MANIPULATION_LABELS,
        sam3_sample_rate=10,
        vlm_model="google/gemma-4-E2B-it",
    ),
)
```

MimicRec の Replay ページから呼び出し、結果をタイムラインに表示。Review UI は MimicRec のフロントに埋め込むか、独立サーバーとして起動。

## 11. Performance considerations

| Component | Strategy |
|-----------|----------|
| SAM3 | Run every 10th frame, interpolate masks |
| VLM (Gemma 4) | 1-2 keyframes per clip, not all frames |
| Object tracking | Bbox interpolation, not pixel-level for skipped frames |
| Boundary detection | Pure numpy, fast |
| Temporal smoothing | Pure python, fast |
| Full pipeline | ~30s-2min per episode (GPU), ~5-10min (CPU) |

## 12. Exit criteria (Phase 1 + 2)

1. `mimicanno annotate --video X --parquet Y --task "pick red block"` produces structured JSON
2. Boundary detection finds gripper transitions and EEF velocity valleys
3. SAM3 tracks objects at sampled rate with interpolation
4. VLM labels clips with allowed labels only, JSON output
5. Temporal smoothing removes noise segments
6. Review UI shows timeline + waveforms + object tracks
7. Human can adjust boundaries and relabel via UI
8. Corrected annotations export to parquet
9. MimicRec integration: Replay page calls mimicanno and displays results
