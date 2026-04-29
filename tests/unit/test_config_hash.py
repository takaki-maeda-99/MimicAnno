# tests/unit/test_config_hash.py

from mimicanno.config import (
    AnnotationConfig,
    BoundaryConfig,
    BoundaryWeights,
    InputBundle,
    ModelConfig,
    compose_run_hash,
    compute_config_hash,
    compute_input_hash,
)


def _make_config(score_threshold: float = 0.30) -> AnnotationConfig:
    return AnnotationConfig(
        boundary=BoundaryConfig(
            weights=BoundaryWeights(),
            thresholds={"gripper_delta": 0.3, "velocity_valley": 0.05},
            merge_window_sec=0.10,
            score_threshold=score_threshold,
            disabled_sources=[],
        ),
        target_phase=1,
        model_config=ModelConfig(
            vlm_model=None,
            vlm_checkpoint=None,
            sam3_model=None,
            sam3_checkpoint=None,
        ),
    )


def _make_inputs(task: str = "pick red block") -> InputBundle:
    return InputBundle(
        video_sha256="sha256:" + "a" * 64,
        parquet_sha256="sha256:" + "b" * 64,
        task_text=task,
        robot_adapter_name="aloha",
        robot_adapter_config_sha256=None,
        labels_yaml_sha256="sha256:" + "c" * 64,
    )


class TestConfigHash:
    def test_same_config_produces_same_hash(self):
        h1 = compute_config_hash(_make_config())
        h2 = compute_config_hash(_make_config())
        assert h1 == h2

    def test_threshold_change_changes_hash(self):
        h1 = compute_config_hash(_make_config(score_threshold=0.30))
        h2 = compute_config_hash(_make_config(score_threshold=0.31))
        assert h1 != h2

    def test_target_phase_changes_hash(self):
        c1 = _make_config()
        c2 = _make_config()
        c2.target_phase = 2
        assert compute_config_hash(c1) != compute_config_hash(c2)

    def test_vlm_model_changes_hash(self):
        c1 = _make_config()
        c2 = _make_config()
        c2.model_config.vlm_model = "google/gemma-4-E2B-it"
        assert compute_config_hash(c1) != compute_config_hash(c2)

    def test_hash_is_sha256_prefixed(self):
        h = compute_config_hash(_make_config())
        assert h.startswith("sha256:")
        assert len(h) == len("sha256:") + 64


class TestInputHash:
    def test_task_text_changes_hash(self):
        h1 = compute_input_hash(_make_inputs("a"))
        h2 = compute_input_hash(_make_inputs("b"))
        assert h1 != h2

    def test_adapter_name_changes_hash(self):
        i1 = _make_inputs()
        i2 = _make_inputs()
        i2.robot_adapter_name = "koch"
        assert compute_input_hash(i1) != compute_input_hash(i2)

    def test_adapter_config_sha_changes_hash(self):
        i1 = _make_inputs()
        i2 = _make_inputs()
        i2.robot_adapter_config_sha256 = "sha256:" + "d" * 64
        assert compute_input_hash(i1) != compute_input_hash(i2)


class TestComposeRunHash:
    def test_run_hash_depends_on_both(self):
        c = _make_config()
        i = _make_inputs()
        baseline = compose_run_hash(compute_config_hash(c), compute_input_hash(i))

        c2 = _make_config(score_threshold=0.31)
        changed_config = compose_run_hash(compute_config_hash(c2), compute_input_hash(i))

        i2 = _make_inputs(task="something else")
        changed_input = compose_run_hash(compute_config_hash(c), compute_input_hash(i2))

        assert baseline != changed_config
        assert baseline != changed_input
        assert changed_config != changed_input

    def test_run_hash_short_is_12_hex(self):
        from mimicanno.config import run_hash_short

        h = "sha256:" + "9" * 64
        assert run_hash_short(h, length=12) == "9" * 12
        assert run_hash_short(h, length=16) == "9" * 16

    def test_run_hash_short_default_length(self):
        from mimicanno.config import RUN_HASH_DEFAULT_PREFIX_LEN, run_hash_short

        assert RUN_HASH_DEFAULT_PREFIX_LEN == 12
        h = "sha256:" + "f" * 64
        assert len(run_hash_short(h)) == 12
