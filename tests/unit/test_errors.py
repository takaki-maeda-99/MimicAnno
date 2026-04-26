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
