# ADR-0047: The mypy plugin makes a decorated element a subclass of its base

**Status:** Accepted

**Date:** October 2026

## Context

An element decorator such as `@domain.aggregate` builds a new class that
inherits from the matching Protean base, `BaseAggregate` here. mypy cannot see
that, because the decorator returns `type[_T]` for the class it was handed.
The mypy plugin fills the gap during semantic analysis.

The plugin used to copy the base's methods and attributes into the decorated
class's own namespace. It did not add the base to the class's bases, because
the Protean bases derive from pydantic's `BaseModel` and mypy then reported a
metaclass conflict. Copying made `order.raise_()` and `order.to_dict()`
visible, but the class was still not a subtype of its base. That left a
family of strict-mode errors in downstream code:

- A decorated element was rejected wherever a signature names its base:
  `domain.cache_for(Leaderboard)`, `cache.add(...)`, `ValueObject(Money)`,
  `x: BaseValueObject = Money(...)`.
- A property copied from the base kept the base as its `self` type, so
  `order.state_` failed with "Invalid self argument".
- `super().__init__(...)` in a decorated domain service resolved to
  `object.__init__`.
- The copied names were in scope in the class body, so pydantic's
  `BaseModel.dict` method shadowed the builtin in
  `changes: dict[str, Any] = Dict()`.

Widening each signature to `type` would have fixed only the first item, one
signature at a time.

## Decision

In the `get_customize_class_mro_hook`, the plugin makes the Protean base the
decorated class's only base and recomputes the MRO. The decorator does the
same at runtime: it rebuilds the class as `type(name, (base_cls,), namespace)`,
so the class's own bases are dropped there too. mypy then gives the class
pydantic's `ModelMetaclass`, the metaclass of its new base, so there is no
metaclass conflict and no need to copy symbols.

A decorated class that already inherits the base, such as a concrete
aggregate extending a decorated abstract one, keeps its bases, as it does at
runtime. Its synthesized `__init__` includes the fields of decorated parents.

With the base in the MRO, mypy also applies the `dataclass_transform` that
`BaseEntity` declares. That transform now sets `kw_only_default=True`, which
is how pydantic constructs the model, so mypy does not apply positional field
ordering rules to Protean fields.

## Consequences

- A decorated element is a subtype of its base for mypy, as it is at runtime.
  Signatures that name a base class accept it with no change to them.
- A mixin listed as a base of a decorated class is dropped for mypy, as it is
  at runtime, so its methods are reported as missing.
- mypy checks a decorated class against its base. A field that reuses the
  name of a base attribute with a different type, such as a field named
  `json` or `copy`, is an `assignment` override error. It was a `no-redef`
  error before, so an ignore comment for that code no longer applies.
- The framework bases declare `id` as `Any`, since the runtime identity can
  be `str`, `int` or `UUID`. An element without its own `id` field still sees
  `id: str`, and one that declares `id: int` keeps it.
- The plugin still synthesizes a keyword `__init__` from the field
  declarations. It takes precedence over the base's `__init__(**data)`, so an
  unknown keyword is still an error.
- IDE engines that do not run the plugin still see the undecorated class.

## Alternatives Considered

Widening every public signature that takes a Protean base class to `type` or
`object` was rejected. It loses precision across the framework, and it leaves
the property, `isinstance`, `super()` and name-shadowing errors in place.

A synthetic intermediate base per element kind, carrying its own
`dataclass_transform` spec, was considered as a way to control the transform.
Declaring `kw_only_default=True` on `BaseEntity` gave the same result without
a synthetic class that mypy's cache would have to serialize.
