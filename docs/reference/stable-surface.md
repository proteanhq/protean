# Stable surface

The [versioning policy](versioning-policy.md) makes one promise:

**Code that runs warning-free on 1.N runs unmodified on 1.N+1.**

This page says what that promise applies to.

The surface is defined here rather than implied by what happens to be
importable. How precisely depends on the area:

- **The Python import surface is enumerated name by name.** Every export of
  `protean`, `protean.fields`, and `protean.exceptions` appears in the
  [export index](#export-index) with its tier, and a test keeps that table in
  step with the shipped `__all__`. For these three modules, a name absent from
  the index is not exported at all.
- **The rest is defined by tier, and enumerated by its own reference page.**
  Documented `domain.toml` keys, documented CLI commands and exit codes, the
  public `protean.testing` DSL, and the public `protean.integrations.*` names
  are Stable, but the authoritative list of each lives with its own
  documentation, not here. "Documented" is the test: a config key or CLI flag
  with a reference page is covered; one you found by reading the source is not.

So absence from the export index means "internal" only for the three modules it
covers. Everywhere else, the tier definitions below are what to reason with.

---

## The three tiers

**Stable.** The compatibility contract applies. These names, their signatures,
and their documented behaviour only change through the deprecation process: a
`DeprecationWarning` naming the version it will be removed in, and a
`protean check` rule, in a release before the one that removes it. A minor may
remove a Stable name that has been through that; it may not break code that was
running warning-free.

**Provisional.** Usable, documented, and supported, but may change in a minor
release with a changelog notice and no deprecation period. These are extension
points whose shape is still settling, mostly because the people using them
(adapter authors, custom field authors) are few enough to coordinate with
directly. A provisional name graduates to Stable once its contract has held
across real third-party use.

**Internal.** No contract at all. May change or disappear in any release,
including a patch. Reaching for these is not forbidden, but it is not
supported, and `protean check` will not warn you before they move.

| Tier | May change in a patch | May change in a minor | Warned first |
|------|----------------------|----------------------|--------------|
| Stable | No | Only through deprecation | Yes, in an earlier release, naming the removal version |
| Provisional | No | Yes, with a changelog notice | Not guaranteed |
| Internal | Yes | Yes | No |

---

## What is Stable

- **Top-level `protean` exports.** Everything in `protean.__all__`, listed in
  the index below.
- **The element decorators and their options.** `@domain.aggregate`,
  `@domain.entity`, `@domain.event`, `@domain.command`, and the rest, together
  with the documented options each accepts.
- **`protean.fields`.** The field factories, the association fields, and the
  `validators` module. Not every name in `protean.fields.__all__` is Stable:
  see the index.
- **`protean.exceptions`.** Every exception and warning class.
- **`protean.testing`.** The public testing DSL.
- **`protean.integrations.*` public names**, including the FastAPI helpers and
  the pytest plugin's documented fixtures and options.
- **Documented `domain.toml` keys.** A key that appears in the
  [configuration reference](configuration/index.md).
- **Documented CLI commands and their exit codes.** Scripts may depend on the
  exit code of `protean check` and friends.
- **The IR schema**, versioned independently by its own `ir_version`. The
  schema evolves under that version, not under Protean's.

## What is Provisional

- **The port ABCs** (`BaseProvider`, `BaseBroker`, `BaseEventStore`,
  `BaseCache`) for third-party adapter authors. These stay provisional until
  the adapter conformance suite ships publicly and has been exercised by an
  adapter Protean does not maintain.
- **`Field`** as the base class for custom field types.
- **`FieldBase`**, the common ancestor of the field hierarchy.
- **`ResolvedField`**, the field-reflection API adapter authors read.
- **The broker partitioning contract** in `protean.port.broker`: the partition
  discovery, fenced-lease and `trim` methods an adapter implements to support
  `sequential_by`, plus the `LeaseLostError` they raise. Enumerated in
  [Broker partitioning](adapters/broker/partitioning.md). It lives outside the
  three modules the export index covers, so the index test does not police it.
- **Observatory HTTP and JSON endpoints.** Useful for tooling, but the
  dashboard's payloads are shaped for the dashboard.
- **`protean.server` internals reached by operations tooling**, such as the
  health server's response bodies.

## What is Internal

- **Any underscore-prefixed name**, at any depth.
- **`protean.core.*` internals** that are not re-exported at the top level.
- **Adapter implementation modules** under `protean.adapters.*`. Configure
  adapters through `domain.toml`; do not import them.
- **`Domain` plumbing accessors**: `registry`, `factory_for`,
  `fetch_element_cls_from_registry`, and the observability accessors. These
  exist for the framework's own wiring.
- **Direct `FieldSpec` instantiation.** `FieldSpec` is the declaration carrier
  the decorators build for you.
- **`ValueObjectList`**, an internal helper for value-object collections.

---

## Ratified conventions

These are settled decisions about the shape of the surface, recorded here so
they are not mistaken for oversights.

**Element base classes are deliberately not re-exported at the top level.**
`protean` exports `Domain` but not `BaseAggregate`; you reach elements through
decorators (`@domain.aggregate`), not by subclassing an imported base. The
asymmetry is intentional. Fields and exceptions *are* imported directly,
because you name them in your own code; element base classes are not, because
the decorator is the supported way to declare an element.

**Boolean element options are bare predicates.** An option that answers yes or
no is named as the predicate itself (`abstract`, `auto_add_id_field`), not
`is_*` or `has_*`.

**All three field declaration styles are supported.** The annotation style is
the documented default:

```python
@domain.aggregate
class Order:
    placed_at: DateTime(required=True)
```

The annotation style is **not compatible with PEP 563** (`from __future__ import
annotations`). Under PEP 563 every annotation becomes a string and the field
object is never constructed. A module that needs postponed annotations must use
the assignment style instead. This is a property of the language feature, not a
gap Protean intends to close.

---

## Export index

The normative list **for the Python import surface**. Every name exported by
`protean`, `protean.fields`, and `protean.exceptions`, with its tier. A test
asserts this table matches the shipped `__all__` declarations exactly, in both
directions, so a new export cannot ship without being classified here and a row
cannot outlive the export it describes.

This index does not cover `domain.toml` keys, CLI commands, `protean.testing`,
or `protean.integrations.*`; see their own reference pages for those.

<!-- surface-index:start -->

| Export | Module | Tier |
|--------|--------|------|
| `Domain` | `protean` | Stable |
| `Engine` | `protean` | Stable |
| `F` | `protean` | Stable |
| `Index` | `protean` | Stable |
| `Priority` | `protean` | Stable |
| `Q` | `protean` | Stable |
| `QuerySet` | `protean` | Stable |
| `ReadOnlyQuerySet` | `protean` | Stable |
| `ReadView` | `protean` | Stable |
| `Record` | `protean` | Stable |
| `UnitOfWork` | `protean` | Stable |
| `apply` | `protean` | Stable |
| `atomic_change` | `protean` | Stable |
| `current_domain` | `protean` | Stable |
| `current_priority` | `protean` | Stable |
| `current_uow` | `protean` | Stable |
| `g` | `protean` | Stable |
| `get_version` | `protean` | Stable |
| `handle` | `protean` | Stable |
| `invariant` | `protean` | Stable |
| `processing_priority` | `protean` | Stable |
| `read` | `protean` | Stable |
| `use_case` | `protean` | Stable |
| `value_object_from_entity` | `protean` | Stable |
| `Auto` | `protean.fields` | Stable |
| `Boolean` | `protean.fields` | Stable |
| `Date` | `protean.fields` | Stable |
| `DateTime` | `protean.fields` | Stable |
| `Decimal` | `protean.fields` | Stable |
| `Dict` | `protean.fields` | Stable |
| `Field` | `protean.fields` | Provisional |
| `FieldBase` | `protean.fields` | Provisional |
| `FieldSpec` | `protean.fields` | Internal |
| `Float` | `protean.fields` | Stable |
| `HasMany` | `protean.fields` | Stable |
| `HasOne` | `protean.fields` | Stable |
| `Identifier` | `protean.fields` | Stable |
| `Integer` | `protean.fields` | Stable |
| `List` | `protean.fields` | Stable |
| `Method` | `protean.fields` | Stable |
| `Nested` | `protean.fields` | Stable |
| `Reference` | `protean.fields` | Stable |
| `ResolvedField` | `protean.fields` | Provisional |
| `Status` | `protean.fields` | Stable |
| `String` | `protean.fields` | Stable |
| `Text` | `protean.fields` | Stable |
| `ValueObject` | `protean.fields` | Stable |
| `ValueObjectFromEntity` | `protean.fields` | Stable |
| `ValueObjectList` | `protean.fields` | Internal |
| `validators` | `protean.fields` | Stable |
| `CommandExpiredError` | `protean.exceptions` | Stable |
| `ConfigurationError` | `protean.exceptions` | Stable |
| `DatabaseError` | `protean.exceptions` | Stable |
| `DeserializationError` | `protean.exceptions` | Stable |
| `DuplicateCommandError` | `protean.exceptions` | Stable |
| `ExpectedVersionError` | `protean.exceptions` | Stable |
| `IncorrectUsageError` | `protean.exceptions` | Stable |
| `InsufficientDataError` | `protean.exceptions` | Stable |
| `InvalidDataError` | `protean.exceptions` | Stable |
| `InvalidOperationError` | `protean.exceptions` | Stable |
| `InvalidStateError` | `protean.exceptions` | Stable |
| `NoDomainException` | `protean.exceptions` | Stable |
| `NotSupportedError` | `protean.exceptions` | Stable |
| `ObjectNotFoundError` | `protean.exceptions` | Stable |
| `ProteanDeprecationWarning` | `protean.exceptions` | Stable |
| `ProteanException` | `protean.exceptions` | Stable |
| `ProteanExceptionWithMessage` | `protean.exceptions` | Stable |
| `SendError` | `protean.exceptions` | Stable |
| `TooManyObjectsError` | `protean.exceptions` | Stable |
| `TransactionError` | `protean.exceptions` | Stable |
| `ValidationError` | `protean.exceptions` | Stable |

<!-- surface-index:end -->

---

## Related reading

- [Versioning policy](versioning-policy.md): what the tiers promise, and how to enforce it in CI.
- [Consistency & delivery guarantees](guarantees.md): the behavioural contract, which is itself part of the Stable surface.
- [Configuration](configuration/index.md): the documented `domain.toml` keys.
