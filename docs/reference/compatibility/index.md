# Compatibility Reference

Reference documentation for Protean's IR compatibility checking system, the
rules that classify changes as safe or breaking, the three-tier taxonomy, and
the deprecation lifecycle.

For the how-to guide on setting up compatibility checks, pre-commit hooks,
and CI integration, see
[Compatibility Checking](../../guides/compatibility-checking.md).

---

## Breaking change rules

Protean classifies changes to persisted domain elements using these rules:

| Change | Classification |
|--------|---------------|
| Add optional field (or with default) | Safe |
| Add required field without default | **Breaking** |
| Remove field from any persisted element | **Breaking** |
| Remove a field deprecated past its removal version | Safe (expected removal) |
| Rename a field via [`renamed_from`](../fields/arguments.md#renamed_from), same type | Safe (`field_renamed`) |
| Rename a field *and* change its type | **Breaking** (`field_type_changed`) |
| Change field type | **Breaking** |
| Remove an element | **Breaking** |
| Add a new element | Safe |
| Visibility public to internal | **Breaking** |
| Visibility internal to public | Safe |
| Change `__type__` string | **Breaking** |
| Event version bump covered by a registered upcaster | Safe (mitigated) |
| Remove a field from an event-sourced aggregate | Safe (mitigated) |
| Turn event sourcing on or off for an aggregate | **Breaking** (`event_sourcing_changed`) |
| Move an event-sourced aggregate's `stream_category` | **Breaking** (`stream_category_changed`) |
| Point an event-sourced aggregate's identity at another field | **Breaking** (`identity_field_changed`) |
| Drop an `@apply` handler while its event survives | **Breaking** (`apply_handler_removed`) |

Most of these rules apply to every persisted element: aggregates, entities,
value objects, commands, events, database models, and projections. The last four
rows are the exception. They read attributes only an aggregate has, so they are
checked on event-sourced aggregates and nowhere else.

### Replay hazards on an event-sourced aggregate

An event-sourced aggregate's authoritative state is a stream of events, rebuilt
by reading that stream and applying the events in it. A snapshot may be stored
alongside it, holding serialized aggregate state, and that snapshot is a
rebuildable cache: Protean discards one that no longer constructs and replays
the stream instead. So the checker reports the changes that stop that rebuild,
whether or not the aggregate's fields moved.

The stream an aggregate reads is named `f"{stream_category}-{identifier}"`, so
moving the stream category leaves the whole history under the old name, and
pointing the identity at another field asks for a stream keyed by a value no
writer ever used. Either way a load of an existing aggregate finds nothing.
Turning event sourcing on or off changes where state lives, and the old state
cannot be read the new way. Dropping an `@apply` handler while its event survives leaves
historical events of that type with nothing to apply them, and the rebuild
raises.

Some related cases are already covered by the general rules above and are not
reported again here: a change to the identity field's *type* is a
`field_type_changed`, and an event removed from the domain outright is an
`element_removed` on that event. Deleting an event class and its `@apply`
method together is one act, so it reports once, as the removal.

### Evolution-aware classification

The checker understands these evolution mechanisms:

- **Deprecation grace**: A field marked `deprecated` and removed at or past its
  `removal` version is an *expected removal* (safe), not a breaking one. This
  applies to every persisted element, including internal and event-sourced
  events (not only published event contracts). It compares against the release
  version; the `protean ir diff` CLI does not yet supply one, so this downgrade
  applies when the diff is run with an explicit current version.
- **Upcaster mitigation**: When an event's `__version__` bumps and a registered
  [upcaster](../../patterns/event-versioning-and-evolution.md) chain covers the
  old→new version path, the schema-transformation changes that make up that
  bump, field removals, type changes, required-field additions, and the `__type__`
  version-string change, are downgraded from breaking to safe, each citing the
  mitigating upcaster. An orthogonal change riding along with the bump (for
  example a public→internal visibility flip) stays breaking, and a version bump
  with an upcaster *gap* (a prior version with no path to the new one) stays
  breaking. So does a bump that moves the type string's base, the part before
  the version, as renaming the domain or the event class does. Chains are
  registered under that base and a stored message is looked up by the base it
  was written with, so moving it strands every stored payload whatever is
  registered under the new base.
- **Event-sourced replay**: An event-sourced aggregate holds no stored schema of
  its own. Its state is a stream of events plus an optional snapshot, and the
  snapshot is a rebuildable cache: Protean constructs the aggregate from the
  snapshot and, when that no longer works because the schema moved, discards it
  and replays the stream. So removing a field from an event-sourced aggregate is
  downgraded to safe. The aggregate has to be event-sourced in both snapshots; a
  classic aggregate converted to event sourcing in the same change stored its old
  state as table rows that replay cannot rebuild.

  A field **type change** is not downgraded. A stored snapshot can survive one
  and skip replay entirely: a stored `Float` of `5.0` coerces cleanly into a new
  `Integer` field, so the aggregate loads from the pre-change snapshot and can
  hold different state than a full replay would produce. A **new required
  field** is not downgraded either, because replay starts from a blank aggregate
  with every field `None`, applies the handlers, and runs no required-field
  check at the end.

  This downgrade says nothing about whether replay still works. The changes that
  stop it are reported separately, as their own breaking changes (see Replay
  hazards above), so a diff that both removes a field and moves the stream
  category still reports breaking and names the stream move as the reason.

---

## Three-tier breaking change taxonomy

Protean follows a tiered approach to breaking changes (see
[ADR-0004](../../adr/0004-release-workflow-and-breaking-change-policy.md)
for the full rationale):

### Tier 1: Surface breaks

Renamed classes, moved imports, changed signatures.

**Mitigation:** Introduce the new API alongside the old. The old API emits
`DeprecationWarning` with a specific removal version and delegates to the
new implementation. Minimum survival: **2 minor versions**.

```python
import warnings

def old_method(self):
    warnings.warn(
        "old_method() is deprecated. Use new_method() instead. "
        "Will be removed in v0.17.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    return self.new_method()
```

### Tier 2: Behavioral breaks

Same signature, different behavior.

**Mitigation:** Introduce new behavior behind a configuration flag,
defaulting to old behavior. Minimum survival: **3 minor versions**.

Transition timeline:

| Version | State |
|---------|-------|
| v0.N | New behavior is opt-in (flag defaults to old) |
| v0.N+1 | Warning emitted if flag is unset |
| v0.N+2 | Default flips to new behavior |

### Tier 3: Structural breaks

Persistence format, event schema, serialization changes.

**Mitigation:** Version the schema or format explicitly. Document exact
migration steps in the release's Upgrade Notes. Provide a migration script
or CLI command where feasible.

The IR compatibility checker (`protean ir diff`) focuses on Tier 3
structural changes.

---

## Deprecation lifecycle

When deprecating a domain element or field:

1. **Mark as deprecated** with a `DeprecationWarning` that includes the
   removal version (see
   [ADR-0004](../../adr/0004-release-workflow-and-breaking-change-policy.md)
   for the deprecation pattern).
2. **Keep the deprecated API** for at least `min_versions_before_removal`
   minor versions (default: 3, configurable in `.protean/config.toml`).
3. **Add to `exclude`** in `.protean/config.toml` if the element should
   not trigger breaking change alerts during its deprecation period.
4. **Remove** in a later release, once the declared removal version has
   arrived and has been announced.

The `protean ir diff` command distinguishes expected removals (deprecated
elements past their removal version) from unexpected removals.

### Earned safety comes first; `exclude` is the last resort

Reach for the in-code primitives before you reach for `exclude`. Each one earns
a downgrade the checker can verify against the actual schema:

- `renamed_from` on the new field marks a rename, not a remove-and-add.
- A `deprecated` mark with a `removal` version earns the expected-removal grace.
- A registered [upcaster](../../patterns/event-versioning-and-evolution.md) chain
  earns the mitigation for an event's version bump.
- An aggregate that is event-sourced on both sides of the change earns the
  downgrade for its field removals, because its state is rebuilt from events
  instead of read from a table. Converting an aggregate to event sourcing earns
  nothing: its existing state is table rows that replay cannot rebuild.

`exclude` earns nothing. It silences the alert without proving the change is
safe, so it is the coarse last resort for the element types the checker cannot
verify: classic table-backed aggregates, projections, commands, and value
objects. Use it only when you have decided by hand that a break is acceptable,
and prefer any of the earned primitives above wherever they apply.

Events additionally accept a `superseded_by` option naming the replacement (an
Event class or a name string):

```python
@domain.event(
    part_of=Order,
    deprecated={"since": "0.16", "removal": "0.19"},
    superseded_by=OrderPlacedV2,
)
class OrderPlaced(BaseEvent): ...
```

The successor is surfaced two ways: raising a deprecated event emits a
`ProteanDeprecationWarning` (once per event type) that names it, and the
`DEPRECATED_ELEMENT` diagnostic appends `superseded by \`<name>\``. It is
documentation-only and never resolved to a link.

---

## `.protean/config.toml` reference

All settings are optional, sensible defaults apply when the file is absent.

```toml
[compatibility]
strictness = "strict"  # "strict" | "warn" | "off"
exclude = ["myapp.internal.LegacyEvent"]

[compatibility.deprecation]
min_versions_before_removal = 3

[staleness]
enabled = true

[domains]
identity = "identity.domain"
catalogue = "catalogue.domain"
ordering = "ordering.domain"
```

### `[compatibility]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `strictness` | string | `"strict"` | `"strict"` exits non-zero on breaking changes. `"warn"` reports but allows. `"off"` skips checking entirely. |
| `exclude` | list of strings | `[]` | Fully-qualified names of elements to exclude from compatibility checks. |

### `[compatibility.deprecation]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `min_versions_before_removal` | integer | `3` | Minimum minor versions a deprecated element must survive before removal. |

### `[staleness]`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | boolean | `true` | Whether the staleness check (`protean ir check`) is active. Set to `false` to skip. |

### `[domains]`

Maps logical domain names to their module paths. When present, pre-commit hooks
iterate over all configured domains automatically, no `--domain` argument
needed. Each domain's IR is stored under `.protean/<name>/ir.json`.

| Key | Type | Description |
|-----|------|-------------|
| `<name>` | string | Dotted module path to the domain (e.g. `"identity.domain"`). The key is the logical name used as the subdirectory. |
