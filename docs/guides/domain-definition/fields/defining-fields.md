# Defining fields

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Protean supports three ways to define fields on domain elements. All three
are fully supported and can be mixed freely within a single class. Choose the
style that reads best for each situation.

## Annotation style (recommended)

Fields are declared as type annotations using Protean's field functions:

```python hl_lines="4-6"
{! docs_src/guides/domain-definition/fields/defining-fields/001.py !}
```

This is the recommended style. It reads as a declaration — "description IS
a String" — which aligns naturally with domain modeling, where you are stating
what something **is**, not assigning it a value.

The annotation style also aligns with how modern Python libraries declare
structured data (dataclasses, Pydantic, attrs). Tools that process annotations
— documentation generators, schema exporters, and IDE inspectors — can
discover fields declared this way.

## Assignment style

Fields are assigned as class variables, using the same field functions:

```python hl_lines="4-6"
{! docs_src/guides/domain-definition/fields/defining-fields/002.py !}
```

This style is familiar if you have used Django models or earlier versions of
Protean. It reads as "name equals a String with max_length 100." The semantics
are identical to annotation style — both produce the same runtime behavior,
validation, and persistence.

## Raw Pydantic style

Protean domain elements are Pydantic models under the hood, so you can use
standard Python type annotations and Pydantic's `Field()` directly:

```python hl_lines="6-7"
{! docs_src/guides/domain-definition/fields/defining-fields/003.py !}
```

This is useful as an escape hatch when you need full control over Pydantic's
configuration — for example, custom `default_factory` callables, complex
`Annotated` metadata, or plain Python types with no constraints.

Any annotation that is not a Protean `FieldSpec` is passed through to
Pydantic untouched.

## Mixing styles

All three styles can coexist in a single class. Each field is processed
according to its form:

```python hl_lines="14-22"
{! docs_src/guides/domain-definition/fields/defining-fields/004.py !}
```

There is no performance or behavioral difference between styles. The choice
is purely about readability and preference.

---

## Which style should I use?

| Style | Best for | Example |
|---|---|---|
| **Annotation** | Most fields — clean, declarative, and modern | `name: String(max_length=100)` |
| **Assignment** | Teams familiar with Django-style models | `name = String(max_length=100)` |
| **Raw Pydantic** | Advanced cases needing direct Pydantic control | `metadata: Annotated[dict, Field(...)]` |

**Recommendation:** Use annotation style as your default. It reads as a
declaration, works well with tooling, and is the style used throughout
Protean's documentation and examples. Reach for assignment style when it
feels more natural for a specific field, and raw Pydantic when you need
capabilities that Protean's field functions don't expose directly.

---

## How it works

Regardless of which style you use, Protean normalizes every field into the
same internal representation before the class is finalized. Protean's field
functions (`String`, `Integer`, `Float`, etc.) each return a `FieldSpec`
object that carries the base Python type, constraints, and metadata. During
class creation, the metaclass resolves every `FieldSpec` into standard
Pydantic type annotations. By the time validation runs, all three styles
are identical.

This means:

- **Validation** works the same way regardless of style. `String(max_length=50)`
  enforces the same length limit whether written as an annotation or assignment.
- **Serialization** (`to_dict()`, JSON export) produces the same output.
- **Persistence** stores and retrieves the same data.
- **JSON Schema** generation includes all constraints from all styles.

For a deeper look at the resolution process and the design reasoning behind
supporting multiple styles, see the
[Field system internals](../../../internals/field-system.md).
