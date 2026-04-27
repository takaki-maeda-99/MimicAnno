"""Phase 2 VLM prompt assembly (spec §3.3).

Builds the system+user text portion of the prompt as a single string. The
caller (FixtureVLMLabeler / LocalGemmaVLMLabeler) is responsible for
splicing in image tokens at the [KEYFRAMES] marker.
"""
from __future__ import annotations

from typing import Optional

from mimicanno.vlm_labeler import REJECT_REASONS, RejectReason, VLMRequest

_REJECT_AMENDMENT_BY_REASON: dict[RejectReason, str] = {
    "json_parse_error": (
        "Re-emit the JSON object only. No prose, no markdown fences."
    ),
    "schema_violation": (
        "All required fields MUST be present with correct types: "
        "phase: string, vlm_confidence: float in [0.0, 1.0], "
        "verb/object/target/evidence: string or null."
    ),
    "invalid_label": (
        "The 'phase' field MUST be one of the allowed labels OR exactly 'unknown'."
    ),
    "out_of_range_confidence": (
        "The 'vlm_confidence' field MUST satisfy 0.0 <= value <= 1.0."
    ),
    "timeout": "",  # no copy change; just retry
}
assert set(_REJECT_AMENDMENT_BY_REASON) == set(REJECT_REASONS), (
    "_REJECT_AMENDMENT_BY_REASON keys must match RejectReason exhaustively"
)

KEYFRAMES_MARKER = "[KEYFRAMES]"


def _fmt_optional_float(v: Optional[float]) -> str:
    if v is None:
        return "null"
    return f"{v:.6g}"


def build_prompt(
    request: VLMRequest,
    attempt: int,
    last_reject_reason: Optional[RejectReason],
) -> str:
    """Construct the prompt text for one VLM call.

    Output structure: SYSTEM block (task + allowed labels + robot state)
    + USER block ([KEYFRAMES] marker for the caller to splice images, plus
    output-format instruction). On retry attempts (attempt > 1), an
    amendment specific to last_reject_reason is appended verbatim.
    """
    rs = request["robot_state_summary"]
    allowed = ", ".join(request["allowed_labels"])
    body = (
        "SYSTEM:\n"
        f"You are labeling a segment of a robot manipulation episode.\n"
        f"Task instruction: \"{request['task_text']}\"\n"
        f"Robot type: {request['robot_type']}, FPS: {request['fps']:.6g},"
        f" Episode duration: {request['episode_duration_sec']:.6g}s.\n"
        f"This is segment {request['segment_index']} of {request['segment_total']}.\n"
        "\n"
        f"Allowed phase labels (label_version={request['label_version']}):\n"
        f"  {allowed}\n"
        "\n"
        "Robot-state summary for this segment:\n"
        f"  duration_sec: {rs['duration_sec']:.6g}\n"
        f"  mean_eef_speed_mps: {_fmt_optional_float(rs.get('mean_eef_speed_mps'))}\n"
        f"  gripper_open_fraction: {rs['gripper_open_fraction']:.6g}\n"
        f"  gripper_transitions: {rs['gripper_transitions']}\n"
        f"  dwell_fraction: {_fmt_optional_float(rs.get('dwell_fraction'))}\n"
        "\n"
        "USER:\n"
        f"{KEYFRAMES_MARKER}\n"
        "\n"
        "Respond with ONE JSON object, no prose, no markdown fences:\n"
        "{\n"
        "  \"phase\":          \"<one of allowed labels, or 'unknown'>\",\n"
        "  \"verb\":           \"<short verb or null>\",\n"
        "  \"object\":         \"<short noun or null>\",\n"
        "  \"target\":         \"<short noun or null>\",\n"
        "  \"vlm_confidence\": <float in [0.0, 1.0]>,\n"
        "  \"evidence\":       \"<<=80 chars, or null>\"\n"
        "}\n"
    )
    if attempt > 1 and last_reject_reason and _REJECT_AMENDMENT_BY_REASON[last_reject_reason]:
        body += (
            "\n"
            f"Your previous response was rejected: reject_reason={last_reject_reason}.\n"
            f"{_REJECT_AMENDMENT_BY_REASON[last_reject_reason]}\n"
            "Re-emit the JSON object exactly per the schema.\n"
        )
    return body
