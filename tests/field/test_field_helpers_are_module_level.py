"""The helpers the field classes call are module-level functions and never
methods on a field class, because a subclass that defines a method of the same
name would replace the helper with no error."""

import inspect

import pytest

from protean.fields import association, base, containers, resolved, spec

HELPERS = {
    association: [
        "_precheck_root",
        "_postcheck_root",
        "_wrong_type_error",
        "_check_item_types",
        "_id_field_name",
        "_identity_or_none",
        "_link_has_one_child",
        "_record_has_one_change",
        "_link_has_many_child",
        "_replace_by_identity",
        "_remove_child_associations",
    ],
    base: ["_load_empty_value", "_check_choices"],
    containers: ["_list_element_type"],
    resolved: ["_schema_extra", "_read_constraint_metadata"],
    spec: [
        "_add_length_and_value_bounds",
        "_add_decimal_precision",
        "_add_identifier_default",
        "_add_default",
        "_add_protean_metadata",
        "_type_coercion_validators",
        "_sanitize_after_validator",
        "_make_protean_validators_runner",
        "_factory_name",
        "_repr_declared_parts",
        "_repr_factory_parts",
    ],
}

FIELD_CLASSES = [
    base.Field,
    association.Association,
    association.HasOne,
    association.HasMany,
    association.Reference,
    resolved.ResolvedField,
    spec.FieldSpec,
]

CASES = [(module, name) for module, names in HELPERS.items() for name in names]


@pytest.mark.parametrize(
    "module, name", CASES, ids=[f"{m.__name__}.{n}" for m, n in CASES]
)
def test_helper_is_a_module_level_function(module, name):
    helper = getattr(module, name)

    assert inspect.isfunction(helper)
    assert helper.__qualname__ == name
    assert helper.__module__ == module.__name__


@pytest.mark.parametrize(
    "module, name", CASES, ids=[f"{m.__name__}.{n}" for m, n in CASES]
)
def test_helper_is_not_an_attribute_of_any_field_class(module, name):
    assert FIELD_CLASSES
    for field_cls in FIELD_CLASSES:
        assert not hasattr(field_cls, name), f"{field_cls.__name__}.{name}"
