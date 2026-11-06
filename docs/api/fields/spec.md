# FieldSpec

Every field factory (`String()`, `Integer()`, etc.) returns a `FieldSpec`, the
internal object that declares a field. A `FieldSpec` holds the field type,
constraints, and configuration until the element class is finalized.

::: protean.fields.spec.FieldSpec
    options:
      show_root_heading: false
