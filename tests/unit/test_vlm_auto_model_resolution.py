"""Tests for `_resolve_auto_model_class()` — transformers 4.x → 5.x compat."""

from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest

from mimicanno.vlm_labeler import _resolve_auto_model_class


def _make_fake_transformers(**attrs: object) -> types.ModuleType:
    mod = types.ModuleType("transformers")
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def test_resolves_5x_image_text_to_text_first():
    """Prefer transformers 5.x `AutoModelForImageTextToText` when both exist."""
    sentinel_5x = object()
    sentinel_4x = object()
    fake = _make_fake_transformers(
        AutoModelForImageTextToText=sentinel_5x,
        AutoModelForVision2Seq=sentinel_4x,
    )
    with patch.dict(sys.modules, {"transformers": fake}):
        assert _resolve_auto_model_class() is sentinel_5x


def test_falls_back_to_4x_vision2seq():
    """transformers 4.x: AutoModelForImageTextToText absent, Vision2Seq used."""
    sentinel_4x = object()
    fake = _make_fake_transformers(AutoModelForVision2Seq=sentinel_4x)
    with patch.dict(sys.modules, {"transformers": fake}):
        assert _resolve_auto_model_class() is sentinel_4x


def test_raises_when_neither_present():
    """Neither name available -> clear ImportError pointing at install fix."""
    fake = _make_fake_transformers()
    with patch.dict(sys.modules, {"transformers": fake}):
        with pytest.raises(ImportError, match="transformers has neither"):
            _resolve_auto_model_class()


# NOTE: a "real transformers" smoke test is intentionally omitted — other
# fixtures in the test suite install partial torch stubs that confuse
# transformers' lazy imports. The 3 mocked cases above cover the resolver
# logic; end-to-end validation comes from the actual Phase 2 Gemma run.
