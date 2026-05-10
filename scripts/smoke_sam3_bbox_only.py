"""SAM3 backend swap — early smoke test (Task 4 of the plan).

Resolves spec §9 open questions before the full SAM3Runtime rewrite:
  Q1. Input bbox convention — top-left xywh vs cxcywh
  Q2. Output `out_boxes_xywh` convention
  Q3. Track-lost behavior — does obj_id disappear from out_obj_ids?
  Q4. Does `propagate_in_video` yield frame 0 itself, or start at frame 1?
  Q5. Bbox-only (no text) sessions accepted by sam3?
  Q6. N>=2 independent sessions yield identical frame_idx series?
  Q7. ground_on_frame text-prompt path on a *single image file* (NamedTemporaryFile)?

Plus edge cases:
  E1. bbox at frame edge (x=0.95, y=0.95, w=0.04, h=0.04)
  E2. very small bbox (w=h=0.01)
  E3. text prompt that hits nothing → expect empty out_obj_ids
  E4. close_session called twice → idempotent or RuntimeError?
  E5. obj_id ndarray dtype + out_boxes_xywh dtype + out_probs presence

Run:
  uv run python scripts/smoke_sam3_bbox_only.py \\
      --video sam3/assets/videos/bedroom.mp4 \\
      --checkpoint sam3/checkpoints/sam3.pt
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np

PASS = "\033[32m[PASS]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"
INFO = "\033[36m[INFO]\033[0m"
WARN = "\033[33m[WARN]\033[0m"


def banner(title: str) -> None:
    print(f"\n{'=' * 78}\n  {title}\n{'=' * 78}")


def show_outputs(outputs: dict, prefix: str = "  ") -> None:
    """Pretty-print one frame's outputs dict."""
    keys = sorted(outputs.keys())
    for k in keys:
        v = outputs[k]
        if hasattr(v, "shape"):
            print(f"{prefix}{k}: shape={tuple(v.shape)} dtype={v.dtype} "
                  f"min={float(v.min()) if v.size else 'n/a'} "
                  f"max={float(v.max()) if v.size else 'n/a'}")
        elif isinstance(v, list):
            print(f"{prefix}{k}: list len={len(v)}")
        else:
            print(f"{prefix}{k}: {v!r}")


def first_frame_jpeg(video_path: Path) -> Path:
    """Extract video frame 0 as a temp JPEG for ground_on_frame smoke."""
    import cv2  # type: ignore
    cap = cv2.VideoCapture(str(video_path))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("could not read frame 0")
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    tf = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tf.close()
    from PIL import Image  # noqa: I001
    Image.fromarray(rgb).save(tf.name, quality=95)
    return Path(tf.name)


def run_smoke(video_path: Path, checkpoint: Path) -> int:  # returns exit code
    failures: list[str] = []

    banner("Loading sam3 video predictor")
    print(f"{INFO} checkpoint={checkpoint}  video={video_path}")
    from sam3.model_builder import build_sam3_video_predictor

    # Workaround: editable install of sam3 makes pkg_resources.resource_filename
    # return None for the namespace `sam3.assets`; pass bpe_path explicitly.
    bpe_path = Path(__file__).resolve().parent.parent / "sam3" / "sam3" / "assets" / "bpe_simple_vocab_16e6.txt.gz"
    if not bpe_path.exists():
        print(f"{FAIL} bpe asset not found at {bpe_path}")
        return 2

    try:
        predictor = build_sam3_video_predictor(
            checkpoint_path=str(checkpoint),
            bpe_path=str(bpe_path),
        )
    except Exception as exc:
        print(f"{FAIL} build_sam3_video_predictor raised: {exc!r}")
        traceback.print_exc()
        return 2

    print(f"{PASS} predictor built  type={type(predictor).__name__}")

    # ---------------------------------------------------------------------
    # Q5 + Q4 + Q2 + Q3: bbox-only session, frame 0 yield, output convention,
    #                    track-lost
    # ---------------------------------------------------------------------
    banner("Q5/Q4/Q2/Q3 — bbox-only session, propagate frame stream")

    sid = None
    try:
        resp = predictor.handle_request({
            "type": "start_session", "resource_path": str(video_path),
            "offload_video_to_cpu": True,
        })
        sid = resp["session_id"]
        print(f"{PASS} start_session  session_id={sid[:12]}...")

        # Edge E1 was originally [0.95,0.95,0.04,0.04] but we put a bbox in
        # the middle of the frame (where the bedroom video has visible content)
        # so that it actually tracks. The edge case test uses a separate session.
        bbox_xywh = [0.40, 0.30, 0.20, 0.30]  # top-left xywh, normalized
        prompt_resp = predictor.handle_request({
            "type": "add_prompt", "session_id": sid,
            "frame_index": 0, "obj_id": 0,
            "bounding_boxes": [bbox_xywh],
            "bounding_box_labels": [1],
            "rel_coordinates": True,
        })
        print(f"{PASS} add_prompt(bbox-only) accepted")
        print(f"{INFO} add_prompt response keys: {sorted(prompt_resp.keys())}")
        if "outputs" in prompt_resp:
            show_outputs(prompt_resp["outputs"])

        # Q4: collect first ~10 frames of propagation. Direction=forward only.
        frames_seen: list[int] = []
        first_frame_outputs: dict | None = None
        last_frame_outputs: dict | None = None

        for i, resp in enumerate(predictor.handle_stream_request({
            "type": "propagate_in_video", "session_id": sid,
            "propagation_direction": "forward",
        })):
            fi = resp["frame_index"]
            outputs = resp["outputs"]
            frames_seen.append(fi)
            if first_frame_outputs is None:
                first_frame_outputs = outputs
                print(f"{INFO} first yielded frame_idx={fi}")
                show_outputs(outputs)
            last_frame_outputs = outputs
            if i >= 15:  # cap to keep smoke fast
                break

        if not frames_seen:
            print(f"{FAIL} propagate_in_video yielded zero frames")
            failures.append("propagate yielded zero frames")
        else:
            print(f"{PASS} propagate_in_video yielded {len(frames_seen)} frames "
                  f"(first={frames_seen[0]}, last={frames_seen[-1]})")
            # Q4 verdict
            if frames_seen[0] == 0:
                print(f"{PASS} Q4: frame 0 IS yielded by propagate_in_video")
            else:
                print(f"{WARN} Q4: frame 0 NOT yielded "
                      f"(first frame_idx={frames_seen[0]})  "
                      f"→ Runtime must inject add_prompt outputs as frame 0")

        # Q2: confirm bbox values look sane for a top-left xywh interpretation.
        # If we pulled bbox=[0.40, 0.30, 0.20, 0.30] and outputs are top-left
        # xywh, then out box should have x in [0.30, 0.50] and y in [0.20, 0.40]
        # for the first few frames (object hasn't moved much). If it's cxcywh,
        # we'd see x near 0.50 (= cx of input).
        if first_frame_outputs is not None:
            ob = first_frame_outputs.get("out_boxes_xywh")
            if ob is not None and hasattr(ob, "shape") and ob.size > 0:
                x, y, w, h = (float(ob[0, k]) for k in range(4))
                print(f"{INFO} Q2: first frame box = "
                      f"x={x:.3f} y={y:.3f} w={w:.3f} h={h:.3f}")
                print(f"{INFO}      input was        "
                      f"x=0.400 y=0.300 w=0.200 h=0.300 (top-left xywh)")
                if 0.20 <= x <= 0.55 and 0.15 <= y <= 0.45:
                    print(f"{PASS} Q2: output looks like TOP-LEFT xywh")
                elif 0.40 <= x <= 0.60 and 0.30 <= y <= 0.50:
                    print(f"{WARN} Q2: output COULD be cxcywh "
                          f"(x≈cx) — needs follow-up")
                else:
                    print(f"{WARN} Q2: ambiguous — record raw values")

        # Q3: did the obj_id stay or vanish? Compare first vs last frame.
        if last_frame_outputs is not None:
            obj_ids_last = last_frame_outputs.get("out_obj_ids")
            print(f"{INFO} Q3: last frame out_obj_ids="
                  f"{None if obj_ids_last is None else obj_ids_last.tolist()}")

    except Exception as exc:
        print(f"{FAIL} bbox-only session raised: {exc!r}")
        traceback.print_exc()
        failures.append(f"bbox-only session: {exc!r}")
    finally:
        if sid is not None:
            try:
                predictor.handle_request({
                    "type": "close_session", "session_id": sid,
                    "run_gc_collect": False,
                })
                print(f"{PASS} close_session ok")
            except Exception as exc:
                print(f"{FAIL} close_session raised: {exc!r}")
                failures.append(f"close_session: {exc!r}")

    # ---------------------------------------------------------------------
    # E4: close_session idempotency
    # ---------------------------------------------------------------------
    banner("E4 — close_session idempotency")
    if sid is not None:
        try:
            predictor.handle_request({
                "type": "close_session", "session_id": sid,
                "run_gc_collect": False,
            })
            print(f"{PASS} close_session twice ok (idempotent)")
        except Exception as exc:
            print(f"{WARN} close_session twice raised: {exc!r}  "
                  f"→ Runtime must guard against double-close")

    # ---------------------------------------------------------------------
    # Q6: N=2 sessions should yield same frame_idx series
    # ---------------------------------------------------------------------
    banner("Q6 — N=2 independent sessions, frame_idx alignment")
    sids: list[str] = []
    try:
        for k, bbox in enumerate([[0.40, 0.30, 0.20, 0.30],
                                  [0.10, 0.50, 0.15, 0.20]]):
            resp = predictor.handle_request({
                "type": "start_session", "resource_path": str(video_path),
                "offload_video_to_cpu": True,
            })
            s = resp["session_id"]
            sids.append(s)
            predictor.handle_request({
                "type": "add_prompt", "session_id": s,
                "frame_index": 0, "obj_id": 0,
                "bounding_boxes": [bbox],
                "bounding_box_labels": [1],
                "rel_coordinates": True,
            })
        streams = [iter(predictor.handle_stream_request({
            "type": "propagate_in_video", "session_id": s,
            "propagation_direction": "forward",
        })) for s in sids]
        seen = [[], []]
        for _ in range(8):
            for j, stream in enumerate(streams):
                nxt = next(stream, None)
                if nxt is not None:
                    seen[j].append(nxt["frame_index"])
        print(f"{INFO} session-A frames: {seen[0]}")
        print(f"{INFO} session-B frames: {seen[1]}")
        if seen[0] == seen[1] and len(seen[0]) > 0:
            print(f"{PASS} Q6: two sessions yield identical frame_idx series")
        else:
            print(f"{WARN} Q6: frame_idx series DIVERGE "
                  f"→ Runtime round-robin must be more defensive")
    except Exception as exc:
        print(f"{FAIL} N=2 sessions raised: {exc!r}")
        traceback.print_exc()
        failures.append(f"N=2 sessions: {exc!r}")
    finally:
        for s in sids:
            try:
                predictor.handle_request({
                    "type": "close_session", "session_id": s,
                    "run_gc_collect": False,
                })
            except Exception:
                pass

    # ---------------------------------------------------------------------
    # E1, E2: edge bbox + tiny bbox
    # ---------------------------------------------------------------------
    banner("E1/E2 — edge bbox + tiny bbox")
    for label, bbox in [("E1 edge", [0.95, 0.95, 0.04, 0.04]),
                        ("E2 tiny", [0.50, 0.50, 0.01, 0.01])]:
        sid2 = None
        try:
            resp = predictor.handle_request({
                "type": "start_session", "resource_path": str(video_path),
                "offload_video_to_cpu": True,
            })
            sid2 = resp["session_id"]
            r = predictor.handle_request({
                "type": "add_prompt", "session_id": sid2,
                "frame_index": 0, "obj_id": 0,
                "bounding_boxes": [bbox],
                "bounding_box_labels": [1],
                "rel_coordinates": True,
            })
            print(f"{PASS} {label} bbox={bbox} accepted")
            ob = r.get("outputs", {}).get("out_boxes_xywh")
            if ob is not None and hasattr(ob, "size") and ob.size > 0:
                print(f"{INFO}   first detection={ob.tolist()}")
            else:
                print(f"{INFO}   no immediate detection (out_obj_ids may be empty)")
        except Exception as exc:
            print(f"{FAIL} {label} raised: {exc!r}")
            failures.append(f"{label}: {exc!r}")
        finally:
            if sid2 is not None:
                try:
                    predictor.handle_request({
                        "type": "close_session", "session_id": sid2,
                        "run_gc_collect": False,
                    })
                except Exception:
                    pass

    # ---------------------------------------------------------------------
    # Q7 + E3: text grounding on a single image file
    # ---------------------------------------------------------------------
    banner("Q7/E3 — single-image text grounding (NamedTemporaryFile)")
    img_path = first_frame_jpeg(video_path)
    print(f"{INFO} extracted frame-0 jpeg → {img_path}")

    for label, prompt in [("Q7 hit", "bed"),
                          ("E3 miss", "an extremely unlikely concept zzzqqq")]:
        sid3 = None
        try:
            resp = predictor.handle_request({
                "type": "start_session", "resource_path": str(img_path),
            })
            sid3 = resp["session_id"]
            r = predictor.handle_request({
                "type": "add_prompt", "session_id": sid3,
                "frame_index": 0, "text": prompt,
                "rel_coordinates": True,
            })
            outputs = r.get("outputs", {})
            obj_ids = outputs.get("out_obj_ids")
            n = 0 if obj_ids is None else (
                obj_ids.size if hasattr(obj_ids, "size") else len(obj_ids)
            )
            print(f"{PASS} {label} text='{prompt}' → {n} detection(s)")
            show_outputs(outputs, prefix="    ")
        except Exception as exc:
            print(f"{FAIL} {label} raised: {exc!r}")
            traceback.print_exc()
            failures.append(f"{label}: {exc!r}")
        finally:
            if sid3 is not None:
                try:
                    predictor.handle_request({
                        "type": "close_session", "session_id": sid3,
                        "run_gc_collect": False,
                    })
                except Exception:
                    pass

    img_path.unlink(missing_ok=True)

    # ---------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------
    banner("SUMMARY")
    if failures:
        for f in failures:
            print(f"{FAIL} {f}")
        return 1
    print(f"{PASS} all smoke checks completed without crash")
    print("Review WARN/INFO lines above to confirm spec §9 verdicts before "
          "writing them into the spec.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--video", default="sam3/assets/videos/bedroom.mp4")
    p.add_argument("--checkpoint", default="sam3/checkpoints/sam3.pt")
    args = p.parse_args()
    return run_smoke(Path(args.video), Path(args.checkpoint))


if __name__ == "__main__":
    sys.exit(main())
