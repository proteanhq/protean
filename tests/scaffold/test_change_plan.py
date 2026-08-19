"""Tests for the ChangePlan type: JSON round-trip, schema, and loud errors."""

import pytest
from jsonschema import ValidationError, validate

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


def test_to_json_emits_keys_in_sorted_order():
    # Plans are previewed and diffed, so serialization must be byte-stable
    # regardless of the order a producer inserted keys.
    plan = ChangePlan(
        operations=(
            ConfigOperation(key_path=("a",), value={"z": 1, "a": 2}, operation="merge"),
        ),
        description="d",
    )

    payload = plan.to_json()

    assert payload.index('"description"') < payload.index('"operations"')
    assert payload.index('"operations"') < payload.index('"plan_version"')
    assert '{"a": 2, "z": 1}' in payload


def test_to_json_is_stable_across_differently_ordered_equal_plans():
    left = ChangePlan(
        operations=(ConfigOperation(key_path=("a",), value={"x": 1, "y": 2}),)
    )
    right = ChangePlan(
        operations=(ConfigOperation(key_path=("a",), value={"y": 2, "x": 1}),)
    )
    assert left.to_json() == right.to_json()


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


def test_schema_pins_plan_version_to_the_supported_version(schema):
    # The schema is versioned by path, so the const has to track PLAN_VERSION.
    assert schema["properties"]["plan_version"]["const"] == PLAN_VERSION


def test_schema_rejects_a_mismatched_plan_version(schema):
    # A plan written for another version must fail validation here rather than
    # being read against the wrong schema.
    data = _sample_plan().to_dict()
    data["plan_version"] = "9.9.9"
    with pytest.raises(ValidationError):
        validate(instance=data, schema=schema)


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


@pytest.mark.parametrize(
    ("entry", "type_name"),
    [
        pytest.param(7, "int", id="int"),
        pytest.param("create", "str", id="str"),
        pytest.param(["create", "a.py"], "list", id="list"),
        pytest.param(None, "NoneType", id="null"),
    ],
)
def test_from_dict_rejects_a_non_object_operation_entry(entry, type_name):
    # from_dict promises ValueError on malformed input; a non-object entry must
    # not leak a TypeError from the discriminator lookup.
    data = {"plan_version": PLAN_VERSION, "operations": [entry]}
    with pytest.raises(ValueError, match=f"must be an object, got {type_name}"):
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


def test_from_dict_rejects_a_config_missing_key_path():
    data = {
        "plan_version": PLAN_VERSION,
        "operations": [{"kind": "config", "value": 1, "operation": "set"}],
    }
    with pytest.raises(ValueError, match="missing required field 'key_path'"):
        ChangePlan.from_dict(data)


@pytest.mark.parametrize(
    ("op", "field"),
    [
        ({"kind": "create", "path": "a.py", "content": None}, "content"),
        ({"kind": "create", "path": 123, "content": "x"}, "path"),
        ({"kind": "edit", "path": "a.py", "diff": None}, "diff"),
    ],
)
def test_from_dict_rejects_a_non_string_field(op, field):
    # from_dict is the loud gate: a value the schema marks type:string but that
    # arrives as null/int is rejected here, not surfaced later as an
    # AttributeError in the preview renderer.
    data = {"plan_version": PLAN_VERSION, "operations": [op]}
    with pytest.raises(ValueError, match=f"field {field!r} must be a string"):
        ChangePlan.from_dict(data)


def test_config_operation_is_optional_in_schema_and_from_dict(schema):
    # The schema and from_dict must agree: operation is optional (it has a "set"
    # default in the dataclass). A config op with no operation validates against
    # the schema AND parses, defaulting to "set".
    data = {
        "plan_version": PLAN_VERSION,
        "operations": [{"kind": "config", "key_path": ["a"], "value": 1}],
    }
    validate(instance=data, schema=schema)
    restored = ChangePlan.from_dict(data).operations[0]
    assert isinstance(restored, ConfigOperation)
    assert restored.operation == "set"


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


@pytest.mark.parametrize("payload", [None, [], "plan", 3])
def test_from_dict_rejects_a_non_mapping_payload(payload):
    # from_dict promises ValueError on malformed input; a non-mapping payload
    # must fail loud the same way from_json does, not blow up as AttributeError.
    with pytest.raises(ValueError, match="must be a mapping"):
        ChangePlan.from_dict(payload)
