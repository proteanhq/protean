"""Tests for the ChangePlan type: JSON round-trip, schema, and loud errors."""

import pytest
from jsonschema import validate

from protean.scaffold import (
    PLAN_VERSION,
    SCHEMA_VERSION,
    ChangePlan,
    ConfigOperation,
    CreateFileOperation,
    EditFileOperation,
    load_schema,
)

pytestmark = pytest.mark.no_test_domain


@pytest.fixture(scope="module")
def schema():
    """Load the ChangePlan JSON Schema once per module."""
    return load_schema()


def _sample_plan() -> ChangePlan:
    """A plan mixing all three op kinds in a specific order."""
    return ChangePlan(
        operations=(
            CreateFileOperation(path="app/domain.py", content="line1\nline2\n"),
            EditFileOperation(
                path="app/config.py",
                diff="--- a/app/config.py\n+++ b/app/config.py\n@@ -1 +1 @@\n-x\n+y\n",
            ),
            ConfigOperation(
                key_path=("databases", "default", "provider"),
                value="postgresql",
                operation="set",
            ),
        ),
        description="A mixed plan",
    )


# ---------------------------------------------------------------------------
# Per-operation round-trips
# ---------------------------------------------------------------------------


def test_create_operation_round_trips_through_a_plan():
    plan = ChangePlan(operations=(CreateFileOperation(path="a.py", content="body"),))
    assert ChangePlan.from_dict(plan.to_dict()) == plan
    assert ChangePlan.from_json(plan.to_json()) == plan


def test_edit_operation_round_trips_through_a_plan():
    plan = ChangePlan(operations=(EditFileOperation(path="a.py", diff="@@ diff @@"),))
    assert ChangePlan.from_dict(plan.to_dict()) == plan
    assert ChangePlan.from_json(plan.to_json()) == plan


def test_config_operation_round_trips_through_a_plan():
    plan = ChangePlan(
        operations=(
            ConfigOperation(key_path=("a", "b"), value={"k": 1}, operation="merge"),
        )
    )
    assert ChangePlan.from_dict(plan.to_dict()) == plan
    assert ChangePlan.from_json(plan.to_json()) == plan


# ---------------------------------------------------------------------------
# Full plan round-trip and ordering
# ---------------------------------------------------------------------------


def test_full_plan_round_trips_and_preserves_order():
    plan = _sample_plan()

    restored = ChangePlan.from_json(plan.to_json())

    assert restored == plan
    # Assert the whole ordered sequence by kind, including position.
    assert [op.kind for op in restored.operations] == ["create", "edit", "config"]


def test_operation_kind_tags_are_set_on_serialization():
    plan = _sample_plan()
    kinds = [op["kind"] for op in plan.to_dict()["operations"]]
    assert kinds == ["create", "edit", "config"]


def test_serialized_plan_carries_the_version_marker():
    plan = _sample_plan()
    payload = plan.to_dict()
    assert payload["plan_version"] == SCHEMA_VERSION
    assert payload["plan_version"] == PLAN_VERSION


def test_empty_plan_round_trips():
    plan = ChangePlan()
    assert plan.to_dict()["operations"] == []
    assert ChangePlan.from_json(plan.to_json()) == plan


def test_description_is_omitted_when_absent():
    plan = ChangePlan(operations=(CreateFileOperation(path="a.py", content="x"),))
    assert "description" not in plan.to_dict()


# ---------------------------------------------------------------------------
# Config op specifics
# ---------------------------------------------------------------------------


def test_config_key_path_stays_an_ordered_tuple_through_round_trip():
    op = ConfigOperation(key_path=("databases", "default", "provider"), value="pg")
    restored = ChangePlan.from_dict(ChangePlan(operations=(op,)).to_dict()).operations[
        0
    ]
    assert isinstance(restored, ConfigOperation)
    assert restored.key_path == ("databases", "default", "provider")
    assert isinstance(restored.key_path, tuple)


def test_config_operation_defaults_to_set():
    op = ConfigOperation(key_path=("a",), value=1)
    assert op.operation == "set"


def test_config_operation_rejects_an_unknown_mode():
    with pytest.raises(ValueError, match="Invalid config operation"):
        ConfigOperation(key_path=("a",), value=1, operation="delete")


def test_config_value_may_be_falsy():
    # value is required-by-presence, so null/false/0 must survive the round-trip.
    for value in (None, False, 0, ""):
        plan = ChangePlan(operations=(ConfigOperation(key_path=("a",), value=value),))
        assert ChangePlan.from_json(plan.to_json()) == plan


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_schema_version_matches_plan_version():
    assert SCHEMA_VERSION == PLAN_VERSION


def test_serialized_plan_validates_against_the_schema(schema):
    validate(instance=_sample_plan().to_dict(), schema=schema)


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(CreateFileOperation(path="a.py", content="x"), id="create"),
        pytest.param(EditFileOperation(path="a.py", diff="@@ @@"), id="edit"),
        pytest.param(
            ConfigOperation(key_path=("a", "b"), value=1, operation="merge"),
            id="config",
        ),
    ],
)
def test_each_op_kind_validates_against_the_schema(operation, schema):
    validate(instance=ChangePlan(operations=(operation,)).to_dict(), schema=schema)


# ---------------------------------------------------------------------------
# Negative: from_dict fails loud on malformed input
# ---------------------------------------------------------------------------


def test_from_dict_rejects_an_unknown_kind():
    data = {"plan_version": PLAN_VERSION, "operations": [{"kind": "rename"}]}
    with pytest.raises(ValueError, match="Unknown operation kind"):
        ChangePlan.from_dict(data)


def test_from_dict_rejects_an_operation_without_a_kind():
    data = {"plan_version": PLAN_VERSION, "operations": [{"path": "a.py"}]}
    with pytest.raises(ValueError, match="missing its 'kind'"):
        ChangePlan.from_dict(data)


def test_from_dict_rejects_a_create_missing_content():
    data = {
        "plan_version": PLAN_VERSION,
        "operations": [{"kind": "create", "path": "a.py"}],
    }
    with pytest.raises(ValueError, match="'content'"):
        ChangePlan.from_dict(data)


def test_from_dict_rejects_an_edit_missing_diff():
    data = {
        "plan_version": PLAN_VERSION,
        "operations": [{"kind": "edit", "path": "a.py"}],
    }
    with pytest.raises(ValueError, match="'diff'"):
        ChangePlan.from_dict(data)


def test_from_dict_rejects_a_config_missing_value():
    data = {
        "plan_version": PLAN_VERSION,
        "operations": [{"kind": "config", "key_path": ["a"], "operation": "set"}],
    }
    with pytest.raises(ValueError, match="'value'"):
        ChangePlan.from_dict(data)


def test_from_dict_rejects_a_config_with_a_non_string_key_path():
    data = {
        "plan_version": PLAN_VERSION,
        "operations": [
            {"kind": "config", "key_path": ["a", 2], "value": 1, "operation": "set"}
        ],
    }
    with pytest.raises(ValueError, match="key_path"):
        ChangePlan.from_dict(data)


def test_from_dict_rejects_a_config_with_a_bad_operation():
    data = {
        "plan_version": PLAN_VERSION,
        "operations": [
            {"kind": "config", "key_path": ["a"], "value": 1, "operation": "wipe"}
        ],
    }
    with pytest.raises(ValueError, match="Invalid config operation"):
        ChangePlan.from_dict(data)


def test_from_dict_rejects_an_unrecognized_plan_version():
    data = {"plan_version": "9.9.9", "operations": []}
    with pytest.raises(ValueError, match="Unsupported plan_version"):
        ChangePlan.from_dict(data)


def test_from_dict_rejects_a_missing_plan_version():
    with pytest.raises(ValueError, match="Unsupported plan_version"):
        ChangePlan.from_dict({"operations": []})


def test_from_dict_rejects_non_list_operations():
    data = {"plan_version": PLAN_VERSION, "operations": "not-a-list"}
    with pytest.raises(ValueError, match="'operations' must be a list"):
        ChangePlan.from_dict(data)


def test_from_dict_rejects_a_non_string_description():
    data = {"plan_version": PLAN_VERSION, "operations": [], "description": 3}
    with pytest.raises(ValueError, match="'description' must be a string"):
        ChangePlan.from_dict(data)


def test_from_json_rejects_invalid_json():
    with pytest.raises(ValueError, match="Invalid ChangePlan JSON"):
        ChangePlan.from_json("{not json")


def test_from_json_rejects_a_non_object_payload():
    with pytest.raises(ValueError, match="must be a JSON object"):
        ChangePlan.from_json("[1, 2, 3]")
