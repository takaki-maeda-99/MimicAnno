# tests/unit/test_labelset.py
from importlib.resources import files as pkg_files
from pathlib import Path

import pytest

from mimicanno.labelset import LabelSet, LabelSetError, default_labels_path, load_label_set


def _bundled_path() -> Path:
    return Path(default_labels_path("manipulation"))


class TestDefaultLabels:
    def test_default_path_exists(self):
        assert _bundled_path().exists()

    def test_default_has_ten_labels(self):
        ls = load_label_set(_bundled_path())
        assert len(ls.labels) == 10

    def test_no_failure_recovery(self):
        ls = load_label_set(_bundled_path())
        assert "failure_recovery" not in {lbl.id for lbl in ls.labels}

    def test_sha256_prefixed(self):
        ls = load_label_set(_bundled_path())
        assert ls.sha256.startswith("sha256:")


class TestReservedPhases:
    def test_rejects_unlabeled_label_id(self, tmp_path: Path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "schema_version: '0.1.0'\n"
            "task_type: x\n"
            "labels:\n"
            "  - id: unlabeled\n"
            "    verbs: []\n"
            "    requires_object: false\n",
        )
        with pytest.raises(LabelSetError, match="reserved"):
            load_label_set(bad)

    def test_rejects_unknown_label_id(self, tmp_path: Path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "schema_version: '0.1.0'\n"
            "task_type: x\n"
            "labels:\n"
            "  - id: unknown\n"
            "    verbs: []\n"
            "    requires_object: false\n",
        )
        with pytest.raises(LabelSetError, match="reserved"):
            load_label_set(bad)


class TestSchemaValidation:
    def test_rejects_old_schema_version(self, tmp_path: Path):
        p = tmp_path / "old.yaml"
        p.write_text(
            "schema_version: '0.0.1'\n"
            "task_type: x\n"
            "labels: []\n",
        )
        with pytest.raises(LabelSetError, match="schema_version"):
            load_label_set(p)
