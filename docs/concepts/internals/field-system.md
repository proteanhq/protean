# Field system

Protean's field system lets you define domain model attributes in a
domain-friendly vocabulary (`String(max_length=100)`, `Float(min_value=0)`,
`HasMany("Product")`). Pydantic v2 runs validation, serialization, and JSON
Schema generation for those attributes.

Three pieces make that work: the `FieldSpec` abstraction, the translation
from Protean's vocabulary into Pydantic's, and the reasoning behind supporting
three field definition styles.

---

## FieldSpec: the translation layer

Every Protean field function (`String`, `Integer`, `Float`, `Boolean`, `Date`,
`DateTime`, `Text`, `Identifier`, `List`, `Dict`) returns a `FieldSpec`
instance. A FieldSpec is a plain Python object that carries four things:

1. **The base Python type**: `str`, `int`, `float`, `bool`, `datetime.date`,
   `datetime.datetime`, `list[T]`, etc.
2. **Constraints in Protean's vocabulary**: `max_length`, `min_length`,
   `max_value`, `min_value`.
3. **Protean-specific metadata**: `identifier`, `unique`, `referenced_as`,
   `field_kind`. Concepts that have no Pydantic equivalent.
4. **Behavioral flags**: `required`, `default`, `choices`. These flags decide
   the resolved type and the resolved field.

FieldSpec has three resolution methods:

- `resolve_type()` produces the final Python type annotation. For example,
  `choices=("a", "b")` becomes `Literal["a", "b"]`, and `required=False`
  wraps the type in `Optional[...]`.
- `resolve_field()` produces a Pydantic `Field(...)` with translated
  constraints.
- `resolve_annotated()` combines both into `Annotated[resolved_type,
  resolved_field]`, the form Pydantic consumes.

### Vocabulary translation

The user writes constraints in Protean's domain vocabulary. FieldSpec
translates them to Pydantic's API vocabulary:

| Protean (what you write) | Pydantic (what runs) |
|---|---|
| `max_length=50` | `Field(max_length=50)` |
| `min_length=1` | `Field(min_length=1)` |
| `max_value=100` | `Field(le=100)` |
| `min_value=0` | `Field(ge=0)` |
| `required=True` | No default set (Pydantic enforces presence); a string also gets `Field(min_length=1)` |
| `required=False` | Type becomes `Optional[T]`, `default=None` |
| `default="hello"` | `Field(default="hello")` |
| `choices=("a", "b")` | Type becomes `Literal["a", "b"]` |
| `identifier=True` | `Field(json_schema_extra={"identifier": True}, default_factory=...)` |
| `unique=True` | `Field(json_schema_extra={"unique": True})` |

Some translations happen at the type level (`choices` becomes `Literal`), some
at the field level (`max_length`), and some are stored as metadata only
(`unique`). FieldSpec performs all three kinds of translation in its resolution
methods.

### FieldSpec disappears at class creation time

The metaclass runs before Pydantic processes the class. It replaces every
FieldSpec with the resolved `Annotated[type, Field(...)]` form. By the time
Pydantic's `ModelMetaclass.__new__` executes, it sees a standard Pydantic
model:

```python
--8<-- "concepts/internals/field-system/001.py:what_you_write"
--8<-- "concepts/internals/field-system/002.py:what_pydantic_sees"
```

Pydantic has no awareness that FieldSpec ever existed. This is by design.
FieldSpec is a compile-time translation layer and does not exist at runtime.
After resolution, Protean domain elements ARE Pydantic models with full access
to validation, serialization, JSON Schema generation, and the broader Pydantic
ecosystem.

---

## Why three definition styles

Protean supports three ways to define fields:

```python
--8<-- "concepts/internals/field-system/003.py:three_styles"
```

Each style exists for a specific reason.

### Annotation style

This is the recommended style. Fields are declared as type annotations:

```python
# fragment
name: String(max_length=50)
```

This reads as "name IS a String", a declaration of what the attribute is.
Domain modelers think about structure in the same way. Python itself also
favors annotations. PEP 526 (variable annotations), PEP 593 (`Annotated`), and
PEP 649 (deferred evaluation) each make annotations the mechanism for
declarative metadata.

Annotation style also follows the way Pydantic discovers fields. Pydantic
discovers fields through `__annotations__`. Fields declared as annotations are
already in `__annotations__`. The metaclass replaces the FieldSpec with a
resolved `Annotated[...]` type and lets Pydantic proceed normally.

### Assignment style

Fields are assigned as class variables:

```python
# fragment
name = String(max_length=50)
```

This style is familiar from Django models and earlier versions of Protean.
It reads as "name equals a String with max_length 50." The semantics are
identical to annotation style.

Assignment style requires more metaclass work. The metaclass must find the
FieldSpec in the class namespace, generate a synthetic annotation, inject it
into `__annotations__`, and remove the original FieldSpec before Pydantic's
metaclass runs. This step adds code to the metaclass. The resulting Pydantic
model is the same as for annotation style.

### Raw Pydantic style

Standard Python type annotations and Pydantic `Field()` are passed through
untouched:

```python
# fragment
metadata: Annotated[dict, Field(default_factory=dict)]
score: float = 0.0
```

This style gives you direct access to Pydantic. If Protean's field functions
don't cover a specific Pydantic feature, you can use Pydantic's API directly.
The metaclass leaves any annotation that is not a FieldSpec untouched.

### Why not pick one

A framework could enforce a single style. Protean chose to support all three
because:

1. **It keeps existing code working**: Assignment style is the convention from
   Protean's earlier field system and from Django. Requiring migration to a new
   syntax would impose unnecessary churn on existing codebases.
2. **It gives you Pydantic's full API**: With raw Pydantic style, you can use a
   Pydantic feature directly when Protean's field functions do not cover it.
   Advanced users are never blocked by limits in Protean's field vocabulary.
3. **It costs nothing at runtime**: All three styles resolve to the same
   Pydantic internals. There is no runtime performance difference. The
   metaclass handles normalization once at class creation time.

The recommendation is annotation style for new code. Assignment and raw
Pydantic are available when they make sense.

---

## Protean-specific metadata

Pydantic has no concept of `unique`, `identifier`, or `referenced_as`. These
are Protean concerns. Protean reads `unique` when it generates the database
schema, `identifier` to find the identity field for repository operations, and
`referenced_as` to name the persistence column.

These values are stored in Pydantic's `json_schema_extra` parameter, a dictionary that Pydantic
attaches to the field's JSON Schema output but otherwise ignores for
validation. This is the standard extension point for framework-specific
metadata.

Three adapter layers in Protean read this metadata from the model's schema:
database adapters, serializers, and relationship resolvers. Protean can add new
concepts in the future by extending FieldSpec's constructor and storing the new
values in `json_schema_extra`. Neither Pydantic nor the user-facing syntax has
to change.

---

## What Pydantic integration delivers

Because domain elements are standard Pydantic models after FieldSpec
resolution, they get these Pydantic features:

- **Validation** runs in Pydantic's Rust core and covers type coercion,
  constraint checking, and nested model validation.
- **Serialization** runs through `to_dict()`, which skips Reference fields,
  serializes nested ValueObject/Reference data at the domain level, and
  converts datetimes to JSON-safe strings. This is the canonical serialization
  method for all domain elements.
- **JSON Schema generation** runs through `model_json_schema()`. Every
  constraint declared through FieldSpec maps to the appropriate JSON Schema
  keyword (`max_length` becomes `maxLength`, `choices` becomes `enum`, etc.).
- **Nested ValueObject validation** works because ValueObject classes are
  Pydantic models. An Aggregate or Entity that embeds them gets proper nested
  validation and nested JSON Schema with `$ref` and `$defs`.

!!! warning "Do not use Pydantic's `model_dump()` on domain elements"
    Domain elements inherit `model_dump()` from Pydantic, but `model_dump()`
    serializes domain-specific data incorrectly. It includes Reference fields,
    omits shadow fields, and returns raw `datetime` objects. Always use
    `to_dict()` instead.

---

## Edge cases and design decisions

### `required=True` with an explicit `default`

If the user writes `String(required=True, default="hello")`, the field has a
default value and is effectively optional from Pydantic's perspective. Protean
honors the default. Protean also logs a warning about the contradiction. The
safe behavior is to give the default precedence. The field can always be
constructed.

### `choices` alongside `max_length`

When `choices` is active, the type becomes `Literal[...]`, making Pydantic's
runtime `max_length` validation redundant (Literal restricts exact values).
However, `max_length` stays on the field, because database adapters still
need it for VARCHAR column sizing. The constraint serves
different purposes at different layers.

### `identifier=True` on non-String fields

This is allowed. An `Integer(identifier=True)` is valid (auto-increment
integers as IDs are common). The automatic UUID `default_factory` is only
injected for string-typed identifiers. For non-string identifiers, the user
must provide their own default or factory.

### Mutable defaults

Mutable defaults (`default=[]`, `default={}`) are detected and automatically
converted to `default_factory`. `default=[]` becomes `default_factory=list`,
`default={}` becomes `default_factory=dict`. This protects against Python's
well-known mutable default argument bug.

### `String()` with no arguments

Returns a FieldSpec with `max_length=255`, `required=False`, no explicit
default. Resolves to `Annotated[Optional[str], Field(default=None,
max_length=255)]`. A bare `String()` is an optional string field with a
max of 255 characters and a default of None.

### Distinguishing Text from String

`Text()` sets `field_kind="text"` in `json_schema_extra`. Both resolve to
`str` at the Python/Pydantic level. The distinction exists for database
adapters, VARCHAR vs TEXT/CLOB. Encoding it as metadata rather than a different
Python type keeps the Pydantic model simple while giving adapters the
information they need.

### Conflict between annotation and assignment

If a field name appears in both positions, the annotation takes precedence.
Pydantic follows the same rule: Pydantic discovers fields from
`__annotations__`.

### `from __future__ import annotations` (PEP 563)

Annotation-style field definitions are incompatible with PEP 563 deferred
evaluation. When `from __future__ import annotations` is active, Python
stringifies all annotations at definition time, `String(max_length=50)` becomes the string `"String(max_length=50)"`. The
metaclass never sees the FieldSpec instance, so resolution cannot happen.

This is a fundamental limitation of placing callable objects in annotation
positions under deferred evaluation. From Python 3.14, Python follows PEP 649
(deferred evaluation of annotations) and evaluates annotations lazily. Python
no longer stringifies them, so this limitation does not apply.

**To work around this limitation:** In modules that require `from __future__
import annotations`, use assignment style (`name = String(max_length=50)`) or
raw Pydantic style. Assignment style stores the FieldSpec in the class
namespace, which is unaffected by annotation stringification.

### IDE type checkers and `FieldSpec`

Annotation-style fields place a `FieldSpec` instance (a function call like
`String(max_length=100)`) in the annotation position. Static type checkers that
validate annotation forms may flag these fields. Pyright and Pylance, for
example, report `reportInvalidTypeForm` errors since a FieldSpec is not a type
in the traditional sense. A FieldSpec is a compile-time descriptor. The
metaclass resolves it before Pydantic processes the class.

To suppress these errors, add a `pyrightconfig.json` at the project root:

```json
{
  "reportInvalidTypeForm": false
}
```

Projects scaffolded with `protean new` include this file automatically. If
you are adding Protean to an existing project and your IDE shows type errors
on field annotations, this is likely the fix.

For **mypy** users, Protean ships a mypy plugin that resolves FieldSpec
return types to their underlying Python types (`String → str`,
`Integer → int`, etc.). Enable it in `pyproject.toml`:

```toml
[tool.mypy]
plugins = ["protean.ext.mypy_plugin"]
```

---

## Association fields are not data fields

Association fields (`HasOne`, `HasMany`) are not data fields. Association
fields declare relationships between domain elements. Protean resolves them in
the repository layer and leaves them out of validation. The metaclass
intercepts them, removes them from the class before Pydantic processes it, and
stores them separately in `__protean_associations__`.

This means associations do not appear in JSON Schema output or serialization.
The repository resolves associations when it loads or persists an aggregate.
