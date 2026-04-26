from mimicanno.schema_versions import (
    ARTIFACT_SCHEMA_VERSIONS,
    COMPAT_BLOCK,
    INDEX_SCHEMA_VERSION,
    LABELS_SCHEMA_VERSION,
    parse_major,
)


def test_artifact_versions_present():
    assert set(ARTIFACT_SCHEMA_VERSIONS.keys()) == {
        "manifest",
        "annotation",
        "boundaries",
        "signals",
    }
    for version in ARTIFACT_SCHEMA_VERSIONS.values():
        assert version == "0.1.0"


def test_compat_block_only_lists_in_run_artifacts():
    # External schemas (labels, index) are NOT in compat per spec §6.6.
    assert set(COMPAT_BLOCK.keys()) == {
        "manifest",
        "annotation",
        "boundaries",
        "signals",
    }
    for major in COMPAT_BLOCK.values():
        assert major == 0


def test_external_schemas_have_independent_versions():
    assert LABELS_SCHEMA_VERSION == "0.1.0"
    assert INDEX_SCHEMA_VERSION == "0.1.0"


def test_parse_major():
    assert parse_major("0.1.0") == 0
    assert parse_major("1.2.3") == 1
    assert parse_major("12.0.0") == 12
