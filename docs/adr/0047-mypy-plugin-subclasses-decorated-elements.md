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
- `isinstance(aggregate, Auditable)` on a `BaseAggregate` produced an
  unreachable branch.
- `super().__init__(...)` in a decorated domain service resolved to
  `object.__init__`.
- The copied names were in scope in the class body, so pydantic's
  `BaseModel.dict` method shadowed the builtin in
  `changes: dict[str, Any] = Dict()`.

Widening each signature to `type` would have fixed only the first item, one
signature at a time.

## Decision

The plugin adds the Protean base to the decorated class's bases in the
`get_customize_class_mro_hook`, recomputes the MRO, and recomputes the
metaclass. Setting the metaclass to pydantic's `ModelMetaclass`, the
metaclass of the new base, removes the conflict that led to copying.

When the class's own bases cannot be ordered with the Protean base (a
decorated class that already inherits `BaseModel` directly, for example), the
plugin falls back to copying the base's symbols. Copied methods are marked
implicit, so a bare name in the class body does not resolve to them, which
matches Python's scoping.

With the base in the MRO, mypy also applies the `dataclass_transform` that
`BaseEntity` declares. That transform now sets `kw_only_default=True`, which
is how pydantic constructs the model, so mypy does not apply positional field
ordering rules to Protean fields.

## Consequences

- A decorated element is a subtype of its base for mypy, as it is at runtime.
  Signatures that name a base class accept it with no change to them.
- mypy checks a decorated class against its base. A field that reuses the
  name of a base attribute with a different type, such as a field named
  `json` or `copy`, is an override error.
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
