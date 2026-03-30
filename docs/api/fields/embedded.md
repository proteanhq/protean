# ValueObject field

Field descriptor for embedding value objects within aggregates or entities.

::: protean.fields.embedded.ValueObject
    options:
      show_root_heading: false
      inherited_members: false

---

# ValueObjectFromEntity field

Field descriptor that auto-generates a value object from an entity class.
Convenience wrapper over `value_object_from_entity()` for inline use in
commands and events.

::: protean.fields.embedded.ValueObjectFromEntity
    options:
      show_root_heading: false
      inherited_members: false

---

# value_object_from_entity

Utility function that creates a `BaseValueObject` subclass mirroring an
entity's fields. See the
[Value Objects guide](../../guides/domain-definition/value-objects.md#projecting-entities-into-value-objects)
for usage patterns.

::: protean.core.value_object.value_object_from_entity
    options:
      show_root_heading: false
