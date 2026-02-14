# FieldSpec Implementation Prompt

You are implementing a `FieldSpec` abstraction layer for the Protean framework. This is the centerpiece of a migration from raw Pydantic syntax to a domain-native field DSL that preserves Protean's original expressiveness while using Pydantic v2 as the validation engine underneath.

Read this document completely before writing any code. Every section exists because a specific part of the codebase depends on it.

---

## 1. WHY THIS EXISTS

Protean is migrating its domain model layer to Pydantic v2. The current state (on the `pydantic-migration` branch) requires users to write raw Pydantic syntax:

```python
from typing import Annotated
from pydantic import Field

@domain.aggregate
class User:
    email: Annotated[str, Field(max_length=255, json_schema_extra={"unique": True})] | None = None
    id: Annotated[str, Field(default_factory=..., json_schema_extra={"identifier": True})]
```

This leaks infrastructure vocabulary into the domain layer. FieldSpec restores Protean's DSL:

```python
from protean.fields import String, Identifier

@domain.aggregate
class User:
    email = String(max_length=255, unique=True)
    id = Identifier()
```

The user never imports from `pydantic`. The framework translates.

---

## 2. DESIGN PRINCIPLES

1. **Domain language over infrastructure language.** The user writes `max_value`, not `le`. They write `identifier=True`, not `json_schema_extra={"identifier": True}`.

2. **FieldSpec is a data carrier, not a descriptor.** Unlike the legacy `Field` class (which is a Python descriptor with `__get__`/`__set__`), FieldSpec is a plain object that carries type information and constraints. It gets consumed and discarded during class creation. After the metaclass runs, only Pydantic's native machinery remains.

3. **One canonical field registry.** The entire codebase depends on `__container_fields__` (the `_FIELDS` constant from `src/protean/utils/reflection.py`). FieldSpec must populate this registry in exactly the same format as today: a dict mapping field names to objects that expose `.field_name`, `.attribute_name`, `.identifier`, `.unique`, `.required`, `.default`, `.max_length`, `.min_value`, `.max_value`, `.referenced_as`, `.increment`, `.content_type`, `.description`, and `.as_dict(value)`. Today this is done by `_PydanticFieldShim`. FieldSpec replaces both the user-facing `Field` descriptors AND the `_PydanticFieldShim` bridge.

4. **Associations remain descriptors.** `HasOne`, `HasMany`, `Reference`, and `ValueObject` (the embedded field) are relationship declarations with complex lifecycle management (shadow fields, change tracking, lazy loading). They stay as descriptors. They are NOT FieldSpecs. They continue to live in `__container_fields__` alongside FieldSpec-derived shims, exactly as they do today.

5. **Two syntaxes for data fields, both first-class.** Assignment style (`name = String(max_length=50)`) and annotation style (`name: String(max_length=50)`) are interchangeable. The class preparation step normalizes both into Pydantic-compatible `Annotated[type, Field(...)]` before Pydantic processes the class.

6. **Raw Pydantic is the escape hatch.** If a user writes `count: int = 0` or `name: Annotated[str, Field(max_length=50)]`, leave it alone. Don't touch what isn't a FieldSpec.

---

## 3. THE FIELDSPEC CLASS

### 3.1 Location

Create `src/protean/fields/spec.py`.

### 3.2 The _UNSET Sentinel

```python
class _UNSET_TYPE:
    """Sentinel indicating no default was provided."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "UNSET"

    def __bool__(self):
        return False

_UNSET = _UNSET_TYPE()
```

Always compare with `is _UNSET`, never `== _UNSET`.

### 3.3 Constructor

```python
class FieldSpec:
    def __init__(
        self,
        python_type: type,
        *,
        # Field kind marker (for adapter-layer discrimination)
        field_kind: str = "standard",  # "standard", "text", "identifier"

        # Common arguments
        required: bool = False,
        default: Any = _UNSET,
        identifier: bool = False,
        unique: bool = False,
        choices: tuple | list | Enum | None = None,  # NOTE: supports Enum classes too
        description: str = "",
        referenced_as: str | None = None,

        # Type-specific constraints
        max_length: int | None = None,
        min_length: int | None = None,
        max_value: float | int | None = None,
        min_value: float | int | None = None,

        # Container-specific
        content_type: Any = None,  # For List fields — can be a FieldSpec or a plain type

        # Sanitization
        sanitize: bool = False,  # For String/Text — runs bleach.clean()

        # Validators
        validators: Iterable[Callable] = (),  # Per-field validator callables

        # Error messages
        error_messages: dict[str, str] | None = None,
    ):
```

**Why each parameter exists:**

- `field_kind`: The SQLAlchemy adapter at `src/protean/adapters/repository/sqlalchemy.py:206-339` needs to distinguish `Text` (→ `sa.Text`) from `String` (→ `sa.String(N)`). Stored in `json_schema_extra`.
- `sanitize`: Current `String` and `Text` fields run `bleach.clean()` on values (`src/protean/fields/basic.py:43,75`). Security-critical. Cannot be silently dropped.
- `validators`: Current `Field.__init__` accepts `validators=()` (`src/protean/fields/base.py:94`). These are per-field callables (like `EmailValidator`, `RegexValidator`). Orthogonal to Pydantic's `@field_validator` and to Protean's `@invariant`.
- `error_messages`: Current `Field.__init__` accepts `error_messages` (`src/protean/fields/base.py:75`). Merged with class-level `default_error_messages`.
- `choices`: Must accept both tuples/lists AND `enum.Enum` subclasses, because the current system supports both (`src/protean/fields/base.py:74,266-283`).

### 3.4 Key Methods

#### `resolve_type() -> type`

Returns the Python type annotation for Pydantic.

```
Logic:
1. Start with self.python_type

2. If self.choices is not None:
   - If choices is an Enum subclass:
     choices_values = [item.value for item in self.choices]
   - Else (tuple/list):
     choices_values = list(self.choices)
   - Replace type with Literal[*choices_values]

3. If NOT required AND default is _UNSET AND NOT identifier:
   - Wrap in Optional: Optional[resolved_type]

4. Return resolved type
```

#### `resolve_field_kwargs() -> dict`

Returns the kwargs dict for `pydantic.Field(...)`.

```
Logic:
1. kwargs = {}

2. String-type constraints (only when python_type is str):
   if max_length is not None: kwargs["max_length"] = max_length
   if min_length is not None: kwargs["min_length"] = min_length

3. Numeric constraints:
   if max_value is not None: kwargs["le"] = max_value   # Protean "max_value" → Pydantic "le"
   if min_value is not None: kwargs["ge"] = min_value   # Protean "min_value" → Pydantic "ge"

4. Handle identifier:
   if self.identifier:
     json_extra["identifier"] = True
     if default is _UNSET:
       if python_type is str:
         kwargs["default_factory"] = lambda: str(uuid4())
       # For non-str identifiers, user must provide their own default

5. Handle default:
   if default is not _UNSET:
     if callable(default):
       kwargs["default_factory"] = default
     elif isinstance(default, (list, dict)):
       # Prevent mutable default bug
       kwargs["default_factory"] = lambda d=default: type(d)(d)
     else:
       kwargs["default"] = default
   elif not required and not identifier:
     kwargs["default"] = None

6. Description:
   if description: kwargs["description"] = description

7. Collect Protean-only metadata into json_schema_extra:
   json_extra = {}
   if unique: json_extra["unique"] = True
   if referenced_as: json_extra["referenced_as"] = referenced_as
   if field_kind != "standard": json_extra["field_kind"] = field_kind
   if identifier: json_extra["identifier"] = True
   if sanitize: json_extra["sanitize"] = True
   # Store validators/error_messages references for the shim layer
   if validators: json_extra["_validators"] = list(validators)
   if error_messages: json_extra["_error_messages"] = error_messages
   if json_extra: kwargs["json_schema_extra"] = json_extra

8. Return kwargs
```

#### `resolve_annotated()`

Combines the above into a single `Annotated[type, Field(...)]`:

```python
def resolve_annotated(self):
    from typing import Annotated
    from pydantic import Field as PydanticField
    return Annotated[self.resolve_type(), PydanticField(**self.resolve_field_kwargs())]
```

This is what gets injected into `__annotations__` for Pydantic to process.

### 3.5 What FieldSpec is NOT

- It is NOT a descriptor. No `__get__`, `__set__`, `__set_name__`.
- It is NOT stored on the class after creation. The metaclass consumes it and replaces it with Pydantic's native annotation.
- It does NOT participate in entity lifecycle. After class creation, all validation goes through Pydantic.
- It does NOT replace association fields (`HasOne`, `HasMany`, `Reference`, `ValueObject`). Those remain descriptors.

---

## 4. FIELD FACTORY FUNCTIONS

Create `src/protean/fields/simple.py` for simple field factories and update `src/protean/fields/containers.py` for container fields.

Each function returns a `FieldSpec` instance. They are not classes — they are factory functions that configure a FieldSpec with the right defaults.

### 4.1 Simple Fields

```python
def String(
    max_length: int = 255,
    min_length: int | None = None,
    sanitize: bool = True,  # NOTE: default True, matching current behavior
    **kwargs,  # All common FieldSpec args: required, default, identifier, unique, etc.
) -> FieldSpec:
    return FieldSpec(
        str,
        max_length=max_length,
        min_length=min_length,
        sanitize=sanitize,
        **kwargs,
    )


def Text(sanitize: bool = True, **kwargs) -> FieldSpec:
    return FieldSpec(str, field_kind="text", sanitize=sanitize, **kwargs)


def Integer(
    min_value: int | None = None,
    max_value: int | None = None,
    **kwargs,
) -> FieldSpec:
    return FieldSpec(int, min_value=min_value, max_value=max_value, **kwargs)


def Float(
    min_value: float | None = None,
    max_value: float | None = None,
    **kwargs,
) -> FieldSpec:
    return FieldSpec(float, min_value=min_value, max_value=max_value, **kwargs)


def Boolean(**kwargs) -> FieldSpec:
    return FieldSpec(bool, **kwargs)


def Date(**kwargs) -> FieldSpec:
    return FieldSpec(datetime.date, **kwargs)


def DateTime(**kwargs) -> FieldSpec:
    return FieldSpec(datetime.datetime, **kwargs)


def Identifier(**kwargs) -> FieldSpec:
    """Shorthand for String(identifier=True)."""
    kwargs.setdefault("identifier", True)
    return FieldSpec(str, field_kind="identifier", **kwargs)
```

### 4.2 Container Fields

```python
def List(content_type=None, **kwargs) -> FieldSpec:
    """
    content_type can be:
    - A FieldSpec: List(String(max_length=30)) → list[str] with per-element validation metadata
    - A plain type: List(int) → list[int]
    - None: List() → list (untyped)
    """
    if isinstance(content_type, FieldSpec):
        inner_type = content_type.python_type
        # Store the full inner FieldSpec for downstream per-element validation
        # The adapter layer can read this from json_schema_extra
    elif content_type is not None:
        inner_type = content_type
    else:
        inner_type = Any

    python_type = list[inner_type]

    # Lists default to empty list, not None
    if "default" not in kwargs and not kwargs.get("required", False):
        kwargs["default"] = list  # Will become default_factory=list

    spec = FieldSpec(python_type, content_type=content_type, **kwargs)
    return spec


def Dict(**kwargs) -> FieldSpec:
    # Dicts default to empty dict, not None
    if "default" not in kwargs and not kwargs.get("required", False):
        kwargs["default"] = dict  # Will become default_factory=dict

    return FieldSpec(dict, **kwargs)
```

### 4.3 The `Auto` Field

The `Auto` field is used internally for auto-generated identity fields. It has special properties:

```python
def Auto(
    increment: bool = False,
    identity_strategy: str | None = None,
    identity_function: str | None = None,
    identity_type: str | None = None,
    **kwargs,
) -> FieldSpec:
    kwargs["required"] = False  # Auto fields are never required
    kwargs["identifier"] = True
    spec = FieldSpec(str, field_kind="auto", **kwargs)
    # Store auto-specific metadata
    spec._increment = increment
    spec._identity_strategy = identity_strategy
    spec._identity_function = identity_function
    spec._identity_type = identity_type
    return spec
```

The `increment` flag is consumed by the memory adapter (`src/protean/adapters/repository/memory.py:327-339`) and the DAO (`src/protean/port/dao.py:332-340`) to decide auto-increment behavior.

---

## 5. INTEGRATING WITH CLASS CREATION

This is the most critical section. The current class creation pipeline has multiple steps that must remain intact.

### 5.1 Current Class Creation Flow (DO NOT BREAK THIS)

For entities/aggregates, the flow is:

```
1. User writes class with @domain.aggregate decorator
2. derive_element_class() is called (src/protean/utils/__init__.py:334)
   → If class doesn't inherit from BaseEntity, creates a new class via type()
   → Calls _prepare_pydantic_namespace() for Pydantic compatibility
3. BaseEntity.__init_subclass__() fires (src/protean/core/entity.py:173)
   → Initializes _invariants
   → Sets empty __container_fields__
   → Calls _maybe_inject_auto_id()
4. Pydantic's ModelMetaclass.__new__() processes the class
   → Reads __annotations__ and namespace to build model_fields
5. BaseEntity.__pydantic_init_subclass__() fires (src/protean/core/entity.py:255)
   → Builds __container_fields__ from model_fields + MRO descriptors
   → Tracks id field
```

For commands/events, the flow is simpler (they extend `BaseMessageType`, which is a Pydantic BaseModel with OptionsMixin).

For value objects, the flow is similar but without association handling.

### 5.2 Where FieldSpec Transformation Happens

FieldSpec transformation MUST happen in step 3 — during `__init_subclass__`, BEFORE Pydantic processes the class. Specifically:

**Option A (Recommended): Transform in `__init_subclass__`**

Add a classmethod `_resolve_fieldspecs()` called from `__init_subclass__` in each base class. This method:

1. Scans `cls.__annotations__` for FieldSpec instances (annotation style)
2. Scans `vars(cls)` for FieldSpec instances (assignment style)
3. For each FieldSpec found:
   a. Call `spec.resolve_annotated()` to get `Annotated[type, Field(...)]`
   b. Set this as the annotation: `cls.__annotations__[name] = resolved`
   c. Remove the FieldSpec from the class namespace: `delattr(cls, name)` or `del namespace[name]`
   d. Store the original FieldSpec in a class-level dict for later reference
4. Leave non-FieldSpec annotations alone (escape hatch)

**Why not a custom metaclass?** Because Pydantic v2 uses its own `ModelMetaclass`, and composing metaclasses is fragile. The `__init_subclass__` hook runs during `ModelMetaclass.__new__()` but before Pydantic reads `__annotations__` (specifically, before `complete_model_class()` is called). This means we can modify `cls.__annotations__` in `__init_subclass__` and Pydantic will see the resolved annotations.

**CRITICAL TIMING DETAIL:** In the current code, `__init_subclass__` already calls `_maybe_inject_auto_id()`. FieldSpec resolution MUST run BEFORE auto-id injection, because auto-id injection checks annotations for existing identifier fields. If a FieldSpec with `identifier=True` hasn't been resolved yet, auto-id injection won't see it and will inject a duplicate `id` field.

So the order in `__init_subclass__` must be:
```python
def __init_subclass__(cls, **kwargs):
    super().__init_subclass__(**kwargs)
    setattr(cls, "_invariants", defaultdict(dict))
    setattr(cls, _FIELDS, {})
    cls._resolve_fieldspecs()       # NEW — resolve FieldSpecs first
    cls._maybe_inject_auto_id()     # EXISTING — now sees resolved annotations
```

### 5.3 The `_resolve_fieldspecs()` Method

This is a classmethod added to `BaseEntity`, `BaseValueObject`, `BaseMessageType`, and `BaseProjection`.

```python
@classmethod
def _resolve_fieldspecs(cls) -> None:
    """Transform FieldSpec declarations into Pydantic-compatible annotations.

    Handles two styles:
    - Assignment: name = String(max_length=50)  → FieldSpec in vars(cls)
    - Annotation: name: String(max_length=50)   → FieldSpec in cls.__annotations__
    """
    from protean.fields.spec import FieldSpec

    own_annots = vars(cls).get("__annotations__", {})
    resolved_annots = dict(own_annots)

    # Track original FieldSpecs for downstream metadata access
    field_meta: dict[str, FieldSpec] = {}

    # 1. Scan class namespace for assignment-style FieldSpecs
    #    (name = String(max_length=50))
    names_to_remove = []
    for name, value in list(vars(cls).items()):
        if isinstance(value, FieldSpec):
            resolved_annots[name] = value.resolve_annotated()
            field_meta[name] = value
            names_to_remove.append(name)

    # Remove FieldSpec objects from namespace so Pydantic doesn't see them
    for name in names_to_remove:
        try:
            delattr(cls, name)
        except AttributeError:
            pass

    # 2. Scan annotations for annotation-style FieldSpecs
    #    (name: String(max_length=50))
    for name, annot_value in list(own_annots.items()):
        if isinstance(annot_value, FieldSpec):
            if name in field_meta:
                # Assignment took precedence; skip annotation duplicate
                import warnings
                warnings.warn(
                    f"Field '{name}' declared in both assignment and annotation style. "
                    f"Using assignment style.",
                    stacklevel=2,
                )
                continue
            resolved_annots[name] = annot_value.resolve_annotated()
            field_meta[name] = annot_value

    cls.__annotations__ = resolved_annots

    # Store FieldSpec metadata for downstream access (adapters, reflection)
    if field_meta:
        existing = getattr(cls, "__protean_field_meta__", {})
        cls.__protean_field_meta__ = {**existing, **field_meta}
```

### 5.4 Integration with `_prepare_pydantic_namespace()`

The `derive_element_class()` function creates classes dynamically via `type()`. When it does this, it calls `_prepare_pydantic_namespace()` to adjust the namespace. This function ALSO needs to handle FieldSpecs, because the class being created hasn't gone through `__init_subclass__` yet at the point `_prepare_pydantic_namespace()` runs.

Wait — actually, `type()` DOES trigger `__init_subclass__` on the newly created class. So FieldSpec resolution in `__init_subclass__` will fire for dynamically-created classes too. No changes needed to `_prepare_pydantic_namespace()` for FieldSpec resolution.

However, `_prepare_pydantic_namespace()` currently checks annotations for `json_schema_extra={"identifier": True}` to detect identifier fields. After FieldSpec resolution, the annotations will contain resolved `Annotated[...]` types, so this detection will still work.

**BUT:** `_prepare_pydantic_namespace()` runs BEFORE `__init_subclass__`. It manipulates `new_dict["__annotations__"]` and `new_dict` before `type()` is called. If the user's original class has FieldSpec objects in its dict/annotations, `_prepare_pydantic_namespace()` will see them. It needs to either:
- (a) Also resolve FieldSpecs (duplicating logic), or
- (b) Be aware that FieldSpecs will be resolved later and not trip over them

Option (b) is cleaner. The current identifier detection in `_prepare_pydantic_namespace()` checks for `FieldInfo` instances and `Annotated` types. FieldSpec is neither, so it will be skipped. Then `__init_subclass__` resolves the FieldSpecs. Then `_maybe_inject_auto_id()` runs and checks the NOW-resolved annotations.

**RISK:** There's a subtle ordering issue. `_prepare_pydantic_namespace()` runs first and may inject an auto-id. Then `__init_subclass__` runs and resolves FieldSpecs. Then `_maybe_inject_auto_id()` runs again. The second call checks `__auto_id_handled__` (set by `_prepare_pydantic_namespace()`) and skips. So: `_prepare_pydantic_namespace()` won't detect FieldSpec identifiers, and will incorrectly inject an auto-id.

**FIX:** Add FieldSpec detection to `_prepare_pydantic_namespace()`:

```python
# In _prepare_pydantic_namespace(), add this check:
from protean.fields.spec import FieldSpec

# Check namespace values for FieldSpec with identifier=True
for attr_name, attr_val in new_dict.items():
    if isinstance(attr_val, FieldSpec) and attr_val.identifier:
        has_id = True
        break

# Check annotations for FieldSpec with identifier=True
if not has_id:
    for attr_name, annotation in annots.items():
        if isinstance(annotation, FieldSpec) and annotation.identifier:
            has_id = True
            break
```

---

## 6. THE FIELDSPEC SHIM — REPLACING `_PydanticFieldShim`

After class creation, the reflection system needs to introspect fields. Currently, `__pydantic_init_subclass__()` wraps each Pydantic `FieldInfo` in a `_PydanticFieldShim` and stores them in `__container_fields__`. FieldSpec-originated fields will also go through this path (since they're resolved to Pydantic annotations before Pydantic processes the class).

The `_PydanticFieldShim` already extracts metadata from `json_schema_extra`. Since FieldSpec stores all Protean-specific metadata there (identifier, unique, referenced_as, field_kind, sanitize, validators, error_messages), the shim will pick them up automatically.

**Enhancement needed:** Extend `_PydanticFieldShim` to also extract:

```python
# In _PydanticFieldShim.__init__:
self.sanitize = extra.get("sanitize", False)
self.field_kind = extra.get("field_kind", "standard")
self._validators = extra.get("_validators", [])
self._error_messages = extra.get("_error_messages", {})
```

Also add a `pickled` property for backward compatibility:
```python
@property
def pickled(self) -> bool:
    return False  # FieldSpec fields are never pickled; this is a legacy concept
```

**NO NEW SHIM CLASS IS NEEDED.** The existing `_PydanticFieldShim` works as-is with minor extensions. FieldSpec's `json_schema_extra` is the bridge.

### 6.1 Sanitization Integration

The current `String._cast_to_type()` runs `bleach.clean(value)`. In the FieldSpec world, Pydantic handles validation, not our custom `_cast_to_type`. For sanitization, add a Pydantic `@field_validator` or `AfterValidator` during FieldSpec resolution:

```python
# In FieldSpec.resolve_annotated(), when sanitize=True:
from pydantic import AfterValidator

def _sanitize_string(v: str) -> str:
    import bleach
    return bleach.clean(v) if isinstance(v, str) else v

if self.sanitize and issubclass(self.python_type, str):
    # Wrap: Annotated[str, Field(...), AfterValidator(_sanitize_string)]
    return Annotated[resolved_type, pydantic_field, AfterValidator(_sanitize_string)]
```

### 6.2 Custom Validators Integration

Per-field validators from the `validators` parameter should also become Pydantic AfterValidators:

```python
if self.validators:
    # Compose validators into a single AfterValidator
    def _run_protean_validators(v, validators=list(self.validators)):
        for validator in validators:
            validator(v)  # Raises ValidationError on failure
        return v

    # Add AfterValidator to the Annotated metadata
```

---

## 7. WHAT MUST NOT CHANGE

### 7.1 Association Fields Stay As-Is

The following remain Python descriptors with full lifecycle management. They are NOT converted to FieldSpec:

- `HasOne` (`src/protean/fields/association.py:374-490`) — change tracking via `_temp_cache`, parent linkage, recursive validation
- `HasMany` (`src/protean/fields/association.py:493-764`) — pseudo-methods (`add_*`, `remove_*`), diff tracking, merge logic
- `Reference` (`src/protean/fields/association.py:90-248`) — lazy loading, shadow field (`_ReferenceField`), cross-aggregate refs
- `ValueObject` (embedded, `src/protean/fields/embedded.py:44-208`) — shadow field construction, bidirectional sync, `_ShadowField` lifecycle

These are discovered in `__pydantic_init_subclass__()` via MRO scanning and added to `__container_fields__` alongside the Pydantic field shims. This mechanism does not change.

### 7.2 `__container_fields__` Registry

The `__container_fields__` dict (stored as `_FIELDS` = `"__container_fields__"`) is the single source of truth for ALL field introspection. Every reflection function in `src/protean/utils/reflection.py` reads from it. Every adapter reads from it. It must continue to contain:

- For data fields: `_PydanticFieldShim` instances (wrapping FieldSpec-originated Pydantic FieldInfo)
- For association fields: the actual descriptor instances (`HasOne`, `HasMany`, `Reference`, `ValueObject`)

The new `__protean_field_meta__` dict (storing original FieldSpecs) is a SECONDARY registry for cases where adapter code needs the raw FieldSpec. It does NOT replace `__container_fields__`.

### 7.3 Thread-Local `_init_context`

Entity initialization uses `_init_context` (thread-local stack, `src/protean/core/entity.py:54`) to pass descriptor kwargs and shadow kwargs through Pydantic's `super().__init__()` boundary. This mechanism is unrelated to FieldSpec and must not be touched.

### 7.4 `__setattr__` Routing

The three-path `__setattr__` in `src/protean/core/entity.py:608-662` routes between Pydantic fields, descriptor fields, and shadow fields. FieldSpec-originated fields become Pydantic `model_fields`, so they follow path 1 (Pydantic field mutation). No change needed.

### 7.5 `to_dict()` and `as_dict()`

Entity/aggregate serialization via `to_dict()` (`src/protean/core/entity.py:727-753`) iterates `__container_fields__` and calls `field_obj.as_dict(value)` on each. The `_PydanticFieldShim.as_dict()` method (`src/protean/core/value_object.py:153-172`) handles serialization. This continues to work because FieldSpec-originated fields are stored as `_PydanticFieldShim` instances in `__container_fields__`.

### 7.6 Auto-ID Injection

The `_maybe_inject_auto_id()` method (`src/protean/core/entity.py:187-252`) must detect FieldSpec-declared identifiers. After `_resolve_fieldspecs()` runs, the annotations are resolved Pydantic types, so the existing detection logic (checking for `FieldInfo` with `json_schema_extra={"identifier": True}`) will work.

### 7.7 Invariants

The invariant system (`@invariant.pre`, `@invariant.post`) operates on entity instances after construction. It is completely orthogonal to FieldSpec and requires no changes.

---

## 8. REQUIRED/DEFAULT INTERACTION RULES

These rules are exhaustive and mutually exclusive in priority order:

```
CASE 1: identifier is True
  → json_schema_extra["identifier"] = True
  → If python_type is str and no explicit default:
      default_factory = lambda: str(uuid4())
  → If non-str and no explicit default:
      No default is set (user must provide one, or auto-id injection handles it)
  → Type is NOT wrapped in Optional

CASE 2: required is True (and not identifier)
  → No default is set at all
  → Pydantic raises ValidationError if value not provided
  → Type is NOT wrapped in Optional

CASE 3: explicit default provided (not _UNSET)
  → Field(default=value) or Field(default_factory=callable)
  → Mutable defaults (list, dict) automatically become default_factory
  → Type is NOT wrapped in Optional

CASE 4: none of the above (not required, no default, not identifier)
  → Type becomes Optional[base_type]
  → Field(default=None)
```

**Edge case: required=True with explicit default.**
Honor the default. The field has a fallback, so it's effectively not required. Log a warning.

**Edge case: choices with max_length.**
When choices is set, the type becomes `Literal[...]`, so Pydantic's max_length validation is irrelevant at runtime. Keep max_length in `json_schema_extra` (not as a Field constraint) so database adapters can still use it for VARCHAR column sizing.

---

## 9. TRANSLATION REFERENCE TABLE

This is authoritative. When in doubt, consult this table.

```
╔═══════════════════════════════════╦════════════════════════════════════════════════════╗
║ User writes (Protean)             ║ Becomes (Pydantic)                                 ║
╠═══════════════════════════════════╬════════════════════════════════════════════════════╣
║ String(max_length=50)             ║ Annotated[Optional[str], Field(default=None,       ║
║                                   ║   max_length=50)]                                  ║
║                                   ║                                                    ║
║ String(max_length=50, required=T) ║ Annotated[str, Field(max_length=50)]               ║
║                                   ║   (no default → Pydantic enforces required)        ║
║                                   ║                                                    ║
║ String(default="hello")           ║ Annotated[str, Field(default="hello",              ║
║                                   ║   max_length=255)]                                 ║
║                                   ║                                                    ║
║ String(identifier=True)           ║ Annotated[str, Field(                              ║
║                                   ║   default_factory=lambda: str(uuid4()),            ║
║                                   ║   max_length=255,                                  ║
║                                   ║   json_schema_extra={"identifier": True})]         ║
║                                   ║                                                    ║
║ Identifier()                      ║ Same as String(identifier=True)                    ║
║                                   ║                                                    ║
║ Text()                            ║ Annotated[Optional[str], Field(default=None,       ║
║                                   ║   json_schema_extra={"field_kind": "text"})]        ║
║                                   ║                                                    ║
║ Integer(min_value=0, max_value=99)║ Annotated[Optional[int], Field(default=None,       ║
║                                   ║   ge=0, le=99)]                                    ║
║                                   ║                                                    ║
║ Float(min_value=0)                ║ Annotated[Optional[float], Field(default=None,     ║
║                                   ║   ge=0)]                                           ║
║                                   ║                                                    ║
║ Boolean(default=False)            ║ Annotated[bool, Field(default=False)]              ║
║                                   ║                                                    ║
║ String(choices=("a","b"))         ║ Annotated[Optional[Literal["a","b"]],              ║
║                                   ║   Field(default=None)]                             ║
║                                   ║                                                    ║
║ String(choices=StatusEnum)        ║ Annotated[Optional[Literal[<enum values>]],        ║
║                                   ║   Field(default=None)]                             ║
║                                   ║                                                    ║
║ String(unique=True, required=T)   ║ Annotated[str, Field(max_length=255,               ║
║                                   ║   json_schema_extra={"unique": True})]             ║
║                                   ║                                                    ║
║ List(String(max_length=30))       ║ Annotated[list[str], Field(                        ║
║                                   ║   default_factory=list)]                           ║
║                                   ║                                                    ║
║ List(int, required=True)          ║ Annotated[list[int], Field()]                      ║
║                                   ║   (no default → required)                          ║
║                                   ║                                                    ║
║ Dict()                            ║ Annotated[dict, Field(default_factory=dict)]       ║
║                                   ║                                                    ║
║ HasOne("Entity", via="ref")       ║ NOT a Pydantic field. Stays as descriptor.         ║
║                                   ║ Stored in __container_fields__ as-is.              ║
║                                   ║                                                    ║
║ name: str = "hello"               ║ Left alone. Raw Pydantic escape hatch.             ║
║ name: Annotated[str, Field(...)]  ║ Left alone. Raw Pydantic escape hatch.             ║
╚═══════════════════════════════════╩════════════════════════════════════════════════════╝
```

---

## 10. FILES TO MODIFY

### New Files
- `src/protean/fields/spec.py` — `_UNSET`, `FieldSpec` class

### Modified Files (with specific changes)

**`src/protean/fields/simple.py`** (NEW — but replaces content currently in `basic.py`)
- Field factory functions: `String`, `Text`, `Integer`, `Float`, `Boolean`, `Date`, `DateTime`, `Identifier`, `Auto`
- These return `FieldSpec` instances, NOT legacy `Field` descriptors
- The legacy `Field` subclasses in `basic.py` remain for backward compatibility but are no longer the primary API

**`src/protean/fields/__init__.py`**
- Export FieldSpec factory functions alongside existing exports
- Gradually, the FieldSpec versions become the primary exports

**`src/protean/core/entity.py`**
- Add `_resolve_fieldspecs()` classmethod to `BaseEntity`
- Call it from `__init_subclass__` BEFORE `_maybe_inject_auto_id()`

**`src/protean/core/value_object.py`**
- Add `_resolve_fieldspecs()` classmethod to `BaseValueObject`
- Call it from `__init_subclass__`
- Extend `_PydanticFieldShim` to extract `sanitize`, `field_kind`, `_validators`, `_error_messages` from `json_schema_extra`

**`src/protean/utils/eventing.py`**
- Add `_resolve_fieldspecs()` classmethod to `BaseMessageType`
- Call it from `__init_subclass__`

**`src/protean/core/projection.py`**
- Add `_resolve_fieldspecs()` classmethod to `BaseProjection`
- Call it from `__init_subclass__`

**`src/protean/utils/__init__.py`**
- Add FieldSpec identifier detection to `_prepare_pydantic_namespace()`

---

## 11. IMPLEMENTATION SEQUENCE

### Phase 1: Core FieldSpec (no integration)

1. Create `src/protean/fields/spec.py` with `_UNSET` and `FieldSpec`
2. Implement `resolve_type()`, `resolve_field_kwargs()`, `resolve_annotated()`
3. Write unit tests that verify the resolved output for every field type and constraint combination
4. Test the required/default interaction matrix exhaustively

### Phase 2: Field Factory Functions

1. Create `String`, `Text`, `Integer`, `Float`, `Boolean`, `Date`, `DateTime`, `Identifier` in `src/protean/fields/simple.py`
2. Create `List`, `Dict` in `src/protean/fields/containers.py` (or add to existing)
3. Write unit tests for each factory function
4. Update `src/protean/fields/__init__.py` to export them

### Phase 3: Class Creation Integration

1. Add `_resolve_fieldspecs()` to `BaseValueObject` (simplest, no associations)
2. Write integration tests: define a VO with FieldSpec fields, instantiate it, verify Pydantic validation
3. Add `_resolve_fieldspecs()` to `BaseEntity` and `BaseAggregate`
4. Verify auto-id injection still works (identifier detection after FieldSpec resolution)
5. Add `_resolve_fieldspecs()` to `BaseMessageType` (commands/events)
6. Add `_resolve_fieldspecs()` to `BaseProjection`
7. Add FieldSpec detection to `_prepare_pydantic_namespace()`

### Phase 4: Shim Enhancement

1. Extend `_PydanticFieldShim` to extract new metadata from `json_schema_extra`
2. Verify that `__container_fields__` is populated correctly for FieldSpec-originated fields
3. Verify reflection functions (`declared_fields`, `attributes`, `id_field`, `unique_fields`) work correctly
4. Verify `to_dict()` and `as_dict()` chain works

### Phase 5: Sanitization and Validators

1. Implement `AfterValidator` integration for `sanitize=True`
2. Implement `AfterValidator` integration for per-field validators
3. Test that validation errors are in Protean format (not raw Pydantic format)

### Phase 6: Adapter Verification

1. Verify memory adapter works with FieldSpec-originated fields
2. Verify SQLAlchemy adapter reads field metadata correctly (identifier, unique, max_length, field_kind, content_type, referenced_as)
3. Verify DAO unique validation works
4. Verify eventing system serializes correctly

### Phase 7: Backward Compatibility

1. Verify that legacy descriptor-style fields (`name = String(max_length=50)` from old `basic.py`) still work during transition
2. Verify that raw Pydantic style (`name: Annotated[str, Field(...)]`) still works
3. Verify that mixing styles within a single class works

---

## 12. TESTING STRATEGY

### Unit Tests for FieldSpec

```python
# Test resolve_type for each case
def test_string_optional_by_default():
    spec = String(max_length=50)
    assert spec.resolve_type() == Optional[str]

def test_string_required():
    spec = String(max_length=50, required=True)
    assert spec.resolve_type() == str  # NOT Optional

def test_string_with_default():
    spec = String(max_length=50, default="hello")
    assert spec.resolve_type() == str  # NOT Optional, has default

def test_string_identifier():
    spec = String(identifier=True)
    assert spec.resolve_type() == str  # NOT Optional

def test_string_choices():
    spec = String(choices=("a", "b"))
    assert spec.resolve_type() == Optional[Literal["a", "b"]]

def test_string_choices_required():
    spec = String(choices=("a", "b"), required=True)
    assert spec.resolve_type() == Literal["a", "b"]  # NOT Optional

def test_integer_constraints():
    spec = Integer(min_value=0, max_value=100)
    kwargs = spec.resolve_field_kwargs()
    assert kwargs["ge"] == 0
    assert kwargs["le"] == 100
```

### Integration Tests

```python
# Test actual class creation and instantiation
@domain.aggregate
class Product:
    name = String(max_length=100, required=True)
    price = Float(min_value=0)
    status = String(choices=("active", "inactive"), default="active")
    sku = String(max_length=20, unique=True)
    description = Text()

# Should work
p = Product(name="Widget", price=9.99, sku="W-001")
assert p.name == "Widget"
assert p.price == 9.99
assert p.status == "active"  # default
assert p.description is None  # optional, no default

# Should fail validation
with pytest.raises(ValidationError):
    Product(price=9.99, sku="W-001")  # name is required

with pytest.raises(ValidationError):
    Product(name="Widget", price=-1, sku="W-001")  # min_value=0

with pytest.raises(ValidationError):
    Product(name="Widget", price=9.99, sku="W-001", status="bogus")  # not in choices
```

### Reflection Tests

```python
# Verify __container_fields__ is populated correctly
from protean.utils.reflection import fields, id_field, unique_fields, declared_fields

@domain.aggregate
class Order:
    order_number = String(max_length=20, required=True, unique=True)

f = declared_fields(Order)
assert "order_number" in f
assert f["order_number"].max_length == 20  # via _PydanticFieldShim
assert f["order_number"].unique is True
assert f["order_number"].required is True
assert "id" in f  # auto-injected
assert id_field(Order).identifier is True
```

### Adapter Tests

```python
# Verify SQLAlchemy can read field metadata
# (run with database test configuration)
```

---

## 13. EDGE CASES AND DECISIONS

### Q: What if both annotation and assignment style are used for the same field?
**A:** Assignment takes precedence. Log a warning. (See `_resolve_fieldspecs()` above.)

### Q: What about `from __future__ import annotations`?
**A:** With `from __future__ import annotations`, ALL annotations become strings (lazy evaluation). This means `name: String(max_length=50)` will be stored as the string `"String(max_length=50)"` in `__annotations__`, not as a `FieldSpec` instance. This breaks annotation-style detection.

**Mitigation:** When `from __future__ import annotations` is active, only assignment style works: `name = String(max_length=50)`. The annotation style requires non-deferred evaluation. Document this limitation clearly. Alternatively, use `typing.get_type_hints()` to resolve string annotations — but this is complex and fragile. Assignment style is the safer default.

### Q: How to handle `String()` with no arguments?
**A:** Returns `FieldSpec(str, max_length=255, required=False, default=_UNSET)`. Resolves to `Annotated[Optional[str], Field(default=None, max_length=255)]`.

### Q: Can `identifier=True` be set on non-String fields?
**A:** Yes. `Integer(identifier=True)` is valid. But the auto UUID default only makes sense for strings. For non-string identifiers, no default_factory is injected — the user must provide a default or let auto-id injection handle it.

### Q: What about the `Method` and `Nested` fields in `basic.py`?
**A:** These are serializer-specific fields used internally. They don't need FieldSpec equivalents. They can remain as legacy Field subclasses.

### Q: What about `Auto` field?
**A:** `Auto` is used internally for auto-generated identity fields. It needs a FieldSpec equivalent that stores `increment`, `identity_strategy`, `identity_function`, `identity_type` in `json_schema_extra`. The memory adapter checks `getattr(field_obj, "increment", False)` — the shim must expose this.

### Q: What about field ordering?
**A:** Python 3.7+ preserves dict insertion order. Pydantic respects annotation order. Both styles maintain declaration order. No special handling needed.

### Q: What about `_version` and `_metadata` internal fields?
**A:** These are injected by `BaseAggregate.__pydantic_init_subclass__()` and `BaseMessageType` respectively. They're not user-facing and don't use FieldSpec. They continue to be added to `__container_fields__` directly.

### Q: What about the `pickled` flag on Dict and List?
**A:** The `pickled` flag is a legacy concept for database serialization. In FieldSpec, it can be stored in `json_schema_extra`. The SQLAlchemy adapter checks `getattr(field_obj, "pickled", False)` — the shim extracts it from `json_schema_extra`.

---

## 14. WHAT SUCCESS LOOKS LIKE

When this is complete:

1. Users can write `name = String(max_length=50)` in any domain element and it works
2. Users can write `name: String(max_length=50)` (without `from __future__`) and it works
3. Users can still write `name: Annotated[str, Field(max_length=50)]` and it works
4. All existing tests pass without modification (the Pydantic-originated fields continue to work)
5. New tests verify FieldSpec-style declarations
6. The reflection API (`declared_fields`, `attributes`, `id_field`, etc.) returns consistent results regardless of which style was used
7. Database adapters work correctly with FieldSpec-originated fields
8. Sanitization (`bleach.clean`) works for String/Text fields with `sanitize=True`
9. Per-field validators work and produce Protean-format error messages
10. No user ever needs to import from `pydantic` for normal domain modeling
