# BaseValueObject

Base class for value objects -- immutable domain elements without identity,
defined entirely by their attributes. Two value objects with the same
attributes are considered equal.

Key methods:

- `replace(**kwargs)` -- Create a copy with selected fields changed
  (see [Replacing Fields](../guides/domain-definition/value-objects.md#replacing-fields))
- `to_dict()` -- Return field values as a dictionary
- `defaults()` -- Override to set computed defaults during initialization

See [Value Objects guide](../guides/domain-definition/value-objects.md) for
practical usage and [Value Objects concept](../concepts/building-blocks/value-objects.md)
for design rationale.

::: protean.core.value_object.BaseValueObject
    options:
      show_root_heading: false
      inherited_members: false

---

# value_object_from_entity

::: protean.core.value_object.value_object_from_entity
    options:
      show_root_heading: false
