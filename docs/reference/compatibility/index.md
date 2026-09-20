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
| Event-sourced aggregate field removal / required-field add, when one rebuilding event has a covered version bump and no rebuilding event is left with a breaking payload change | Safe (mitigated) |

These rules apply to all persisted elements: aggregates, entities, value
objects, commands, events, database models, and projections.

### Evolution-aware classification

The checker understands three evolution mechanisms:

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
  breaking.
- **Event-sourced aggregate replay coverage**: An event-sourced aggregate is
  rebuilt by replaying the events its apply-handlers process. So a field removal
  or a required-field add on such an aggregate is downgraded to safe when two
  things hold: no rebuilding event is left with a breaking payload change, and at
  least one event that already rebuilt the aggregate in the old snapshot has an
  upcaster-covered version bump. A rebuilding event with an uncovered bump, one
  whose payload changed without a bump, or no bump anywhere leaves the aggregate
  breaking, because nothing was earned. An unchanged rebuilding event needs no
  upcaster; it earns nothing either. A covered bump on an event whose
  apply-handler was added in the same diff earns nothing: that handler never
  rebuilt historical state. The aggregate must be event-sourced in both the old and new
  snapshots: a classic aggregate converted to event sourcing in the same diff
  stored its old state as table rows that replay cannot rebuild, so its field
  changes stay breaking. Dropping a rebuilding event's apply-handler also leaves
  the aggregate breaking, because its historical events can no longer be replayed.
  Coverage is at aggregate granularity: the IR carries no
  per-field history, so a covered bump on any rebuilding event downgrades the
  aggregate's field changes, not only the fields that event populates. A classic
  table-backed aggregate is never touched by this path; its breaking field
  changes stay breaking, and `exclude` is the only way to silence them.

  A **field type change** is not on this list. An event-sourced aggregate can
  still have a stored snapshot of its own state, and Protean loads that snapshot
  directly, replaying the event stream only when the snapshot no longer
  constructs. A removed field and a new required field both make the snapshot
  fail to construct, so it is discarded and the upcaster runs. A type change
  often does not: a stored `Float` of `5.0` coerces cleanly into a new `Integer`
  field, so the aggregate loads from the pre-change snapshot and the upcaster is
  never consulted. That change stays breaking.

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
- Event-sourced replay coverage extends that same earned downgrade to an
  event-sourced aggregate's field removals and required-field adds, once one
  rebuilding event has a covered version bump and no rebuilding event is left
  breaking.

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
