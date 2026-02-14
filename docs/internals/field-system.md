# Field system

Protean's field system lets you define domain model attributes using a
domain-friendly vocabulary — `String(max_length=100)`, `Float(min_value=0)`,
`HasMany("Product")` — while Pydantic v2 handles validation, serialization,
and JSON Schema generation underneath.

This page explains the internal architecture that makes this work: the
`FieldSpec` abstraction, the translation from Protean vocabulary to Pydantic,
and the reasoning behind supporting three field definition styles.

---

## FieldSpec: the translation layer

Every Protean field function (`String`, `Integer`, `Float`, `Boolean`, `Date`,
`DateTime`, `Text`, `Identifier`, `List`, `Dict`) returns a `FieldSpec`
instance. A FieldSpec is a plain Python object that carries four things:

1. **The base Python type** — `str`, `int`, `float`, `bool`, `datetime.date`,
   `datetime.datetime`, `list[T]`, etc.
2. **Constraints in Protean's vocabulary** — `max_length`, `min_length`,
   `max_value`, `min_value`.
3. **Protean-specific metadata** — `identifier`, `unique`, `referenced_as`,
   `field_kind` — concepts that have no Pydantic equivalent.
4. **Behavioral flags** — `required`, `default`, `choices` — that affect how
   the type and field are resolved.

FieldSpec has three resolution methods:

- `resolve_type()` produces the final Python type annotation. For example,
  `choices=("a", "b")` becomes `Literal["a", "b"]`, and `required=False`
  wraps the type in `Optional[...]`.
- `resolve_field()` produces a Pydantic `Field(...)` with translated
  constraints.
- `resolve_annotated()` combines both into `Annotated[resolved_type,
  resolved_field]`, which is what Pydantic consumes.

### Vocabulary translation

The user writes constraints in Protean's domain vocabulary. FieldSpec
translates them to Pydantic's API vocabulary:

| Protean (what you write) | Pydantic (what runs) |
|---|---|
| `max_length=50` | `Field(max_length=50)` |
| `min_length=1` | `Field(min_length=1)` |
| `max_value=100` | `Field(le=100)` |
| `min_value=0` | `Field(ge=0)` |
| `required=True` | No default set (Pydantic enforces presence) |
| `required=False` | Type becomes `Optional[T]`, `default=None` |
| `default="hello"` | `Field(default="hello")` |
| `choices=("a", "b")` | Type becomes `Literal["a", "b"]` |
| `identifier=True` | `Field(json_schema_extra={"identifier": True}, default_factory=...)` |
| `unique=True` | `Field(json_schema_extra={"unique": True})` |

Some translations happen at the type level (`choices` becomes `Literal`),
some at the field level (`max_length`), and some are stored as metadata only
(`unique`). FieldSpec handles all three through its resolution methods.

### FieldSpec disappears at class creation time

The metaclass runs before Pydantic processes the class. It replaces every
FieldSpec with the resolved `Annotated[type, Field(...)]` form. By the time
Pydantic's `ModelMetaclass.__new__` executes, it sees a standard Pydantic
model:

```python
# What you write:
class Product(BaseEntity):
    name: String(max_length=50, required=True)
    price: Float(min_value=0, default=0.0)
    status: String(choices=("active", "discontinued"), default="active")

# What Pydantic sees after metaclass resolution:
class Product(BaseEntity):
    name: Annotated[str, Field(max_length=50)]
    price: Annotated[float, Field(ge=0, default=0.0)]
    status: Annotated[Literal["active", "discontinued"], Field(default="active")]
```

Pydantic has no awareness that FieldSpec ever existed. This is by design —
FieldSpec is a compile-time translation layer, not a runtime abstraction.
After resolution, Protean domain elements ARE Pydantic models with full
access to validation, serialization, JSON Schema generation, and the broader
Pydantic ecosystem.

---

## Why three definition styles

Protean supports three ways to define fields:

```python
class Product(BaseEntity):
    name: String(max_length=50)                        # annotation
    price: Float(min_value=0)                         # assignment
    metadata: Annotated[dict, Field(default_factory=dict)]  # raw Pydantic
```

Each style exists for a specific reason.

### Annotation style

This is the recommended style. Fields are declared as type annotations:

```python
name: String(max_length=50)
```

This reads as "name IS a String" — a declaration of what the attribute is,
which aligns with how domain modelers think about structure. It is also
where Python is heading as a language: PEP 526 (variable annotations),
PEP 593 (`Annotated`), and PEP 649 (deferred evaluation) all invest in
annotations as the mechanism for declarative metadata.

From an implementation perspective, annotation style works *with* Pydantic
rather than against it. Pydantic discovers fields through `__annotations__`,
so fields declared as annotations are already where Pydantic expects them.
The metaclass replaces the FieldSpec with a resolved `Annotated[...]` type
and lets Pydantic proceed normally.

### Assignment style

Fields are assigned as class variables:

```python
name = String(max_length=50)
```

This style is familiar from Django models and earlier versions of Protean.
It reads as "name equals a String with max_length 50." The semantics are
identical to annotation style.

Assignment style requires more metaclass work — the metaclass must find the
FieldSpec in the class namespace, generate a synthetic annotation, inject it
into `__annotations__`, and remove the original FieldSpec before Pydantic's
metaclass runs. This is additional machinery, but it produces the same
result.

### Raw Pydantic style

Standard Python type annotations and Pydantic `Field()` are passed through
untouched:

```python
metadata: Annotated[dict, Field(default_factory=dict)]
score: float = 0.0
```

This is the escape hatch. If Protean's field functions don't cover a
specific Pydantic feature, you can use Pydantic's API directly. Any
annotation that is not a FieldSpec is left untouched by the metaclass.

### Why not pick one

A framework could enforce a single style. Protean chose to support all three
because:

1. **Backward compatibility.** Assignment style is the convention from
   Protean's earlier field system and from Django. Requiring migration to a
   new syntax would impose unnecessary churn on existing codebases.
2. **Ecosystem access.** Raw Pydantic support means there is always an escape
   hatch. Advanced users are never blocked by limits in Protean's field
   vocabulary.
3. **Zero cost.** All three styles resolve to the same Pydantic internals.
   There is no runtime performance difference. The metaclass handles normalization
   once at class creation time.

The recommendation is annotation style for new code. Assignment and raw
Pydantic are available when they make sense.

---

## Protean-specific metadata

Pydantic has no concept of `unique`, `identifier`, or `referenced_as`. These
are Protean concerns — `unique` informs database schema generation,
`identifier` marks the identity field for repository operations,
`referenced_as` controls persistence column naming.

These values are stored in Pydantic's `json_schema_extra` parameter — a
dictionary that Pydantic attaches to the field's JSON Schema output but
otherwise ignores for validation. This is the standard extension point for
framework-specific metadata.

Protean's adapter layers (database adapters, serializers, relationship
resolvers) read this metadata from the model's schema. New Protean concepts
can be added in the future by extending FieldSpec's constructor and storing
the new values in `json_schema_extra`, without modifying Pydantic or the
user-facing syntax.

---

## What Pydantic integration delivers

Because domain elements are standard Pydantic models after FieldSpec
resolution, they get full Pydantic capabilities:

- **Validation** using Pydantic's Rust core — type coercion, constraint
  checking, nested model validation.
- **Serialization** via `to_dict()`, `model_dump()`, and
  `model_dump_json()`. Selective serialization (`include`, `exclude`,
  `exclude_none`) works out of the box.
- **JSON Schema generation** via `model_json_schema()`. Every constraint
  declared through FieldSpec maps to the appropriate JSON Schema keyword
  (`max_length` becomes `maxLength`, `choices` becomes `enum`, etc.).
- **Nested ValueObject validation.** Because ValueObject classes are Pydantic
  models, embedding them in an Aggregate or Entity produces proper nested
  validation and nested JSON Schema with `$ref` and `$defs`.
- **Ecosystem compatibility.** Domain elements work with any tool that
  consumes Pydantic models — FastAPI, schema registries, documentation
  generators, and more.

---

## Edge cases and design decisions

### `required=True` with an explicit `default`

If the user writes `String(required=True, default="hello")`, the field has
a default value and is effectively optional from Pydantic's perspective.
Protean honors the default and logs a warning about the contradiction. The
safe behavior is to give the default precedence — the field can always be
constructed.

### `choices` alongside `max_length`

When `choices` is active, the type becomes `Literal[...]`, making Pydantic's
runtime `max_length` validation redundant (Literal restricts exact values).
However, `max_length` is preserved in `json_schema_extra` because database
adapters still need it for VARCHAR column sizing. The constraint serves
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
adapters — VARCHAR vs TEXT/CLOB. Encoding it as metadata rather than a
different Python type keeps the Pydantic model simple while giving adapters
the information they need.

### Conflict between annotation and assignment

If a field name appears in both positions, the annotation takes precedence.
This aligns with Pydantic's behavior, where `__annotations__` is the source
of truth for field discovery.

---

## Association fields are not data fields

Association fields (`HasOne`, `HasMany`) are not data fields. They declare
relationships between domain elements and are resolved at the repository
layer, not at the validation layer. The metaclass intercepts them, removes
them from the class before Pydantic processes it, and stores them separately
in `__protean_associations__`.

This means associations do not appear in JSON Schema output or
serialization. They are resolved when aggregates are loaded from or
persisted to a repository.
