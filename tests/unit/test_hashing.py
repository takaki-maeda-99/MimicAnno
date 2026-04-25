import hashlib
from pathlib import Path

import pytest

from mimicanno.hashing import canonical_json, sha256_file, sha256_hex_of_str


class TestCanonicalJson:
    def test_dict_keys_are_sorted(self):
        a = canonical_json({"b": 1, "a": 2})
        b = canonical_json({"a": 2, "b": 1})
        assert a == b
        assert a == '{"a":2,"b":1}'

    def test_no_whitespace(self):
        result = canonical_json({"a": [1, 2, 3]})
        assert " " not in result
        assert "\n" not in result

    def test_nested_dicts_sorted(self):
        result = canonical_json({"outer": {"z": 1, "a": 2}})
        assert result == '{"outer":{"a":2,"z":1}}'

    def test_unicode_kept_as_unicode(self):
        # No escape of non-ASCII; this matters for stable cross-platform hashes.
        result = canonical_json({"task": "つかむ"})
        assert "つかむ" in result

    def test_floats_use_repr(self):
        result = canonical_json({"x": 0.1 + 0.2})
        assert result == '{"x":0.30000000000000004}'

    def test_none_serialized_as_null(self):
        assert canonical_json({"x": None}) == '{"x":null}'

    def test_rejects_nan(self):
        with pytest.raises(ValueError, match="NaN"):
            canonical_json({"x": float("nan")})

    def test_rejects_nan_in_dict_key(self):
        with pytest.raises(ValueError, match="NaN"):
            canonical_json({float("nan"): 1})

    def test_rejects_infinity(self):
        with pytest.raises(ValueError, match="Infinity"):
            canonical_json({"x": float("inf")})


class TestSha256HexOfStr:
    def test_known_value(self):
        # echo -n "" | sha256sum
        assert sha256_hex_of_str("") == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_utf8_bytes(self):
        result = sha256_hex_of_str("つかむ")
        expected = hashlib.sha256("つかむ".encode()).hexdigest()
        assert result == expected


class TestSha256File:
    def test_known_file(self, tmp_path: Path):
        f = tmp_path / "x.bin"
        f.write_bytes(b"hello world")
        assert sha256_file(f) == hashlib.sha256(b"hello world").hexdigest()

    def test_streamed_for_large_file(self, tmp_path: Path):
        # Generate ~3 MB file; we stream in 1 MiB chunks so this must not OOM.
        f = tmp_path / "big.bin"
        f.write_bytes(b"a" * (3 * 1024 * 1024))
        result = sha256_file(f)
        expected = hashlib.sha256(b"a" * (3 * 1024 * 1024)).hexdigest()
        assert result == expected
