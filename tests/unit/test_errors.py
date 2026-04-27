"""Tests for mimicanno.errors."""

import io
import json

from mimicanno.errors import MimicAnnoError, write_error_json


def test_str_format() -> None:
    err = MimicAnnoError(code="E001", message="something went wrong")
    assert str(err) == "[E001] something went wrong"


def test_write_error_json() -> None:
    err = MimicAnnoError(code="E002", message="bad input", context={"key": "value"})
    buf = io.StringIO()
    write_error_json(err, stream=buf)
    payload = json.loads(buf.getvalue())
    assert payload == {"error_code": "E002", "message": "bad input", "context": {"key": "value"}}


def test_phase2_vlm_model_required_error() -> None:
    from mimicanno.errors import VLMModelRequired
    e = VLMModelRequired(target_phase=2)
    assert e.code == "vlm_model_required"
    assert e.context == {"target_phase": 2}


def test_phase2_vlm_config_invalid_error() -> None:
    from mimicanno.errors import VLMConfigInvalid
    e = VLMConfigInvalid(reason="keyframes_per_segment must be >= 1")
    assert e.code == "vlm_config_invalid"
    assert "must be >= 1" in e.message


def test_phase2_vlm_model_not_found_error() -> None:
    from mimicanno.errors import VLMModelNotFound
    e = VLMModelNotFound(model_id="google/foo", reason="404")
    assert e.code == "vlm_model_not_found"
    assert e.context["model_id"] == "google/foo"
