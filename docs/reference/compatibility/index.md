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
| Add optional field (or with default) | Safe, unless it moves an event's Protobuf field number (see the `field_number_changed` row) |
| Add required field without default | **Breaking** |
| Remove field from any persisted element | **Breaking** |
| Remove a field deprecated past its removal version | Safe (expected removal) |
| Remove a field from an event-sourced aggregate that declares the name `reserved` | Safe (`reserved`) |
| Rename a field via [`renamed_from`](../fields/arguments.md#renamed_from), same type | Safe (`field_renamed`), unless the rename also changes a `Dict` or `List` value type, or a `Decimal` field's precision or scale in a breaking way (see the rows below), or moves an event's Protobuf field number (see the `field_number_changed` row) |
| Rename a field *and* change its type | **Breaking** (`field_type_changed`) |
| Change field type | **Breaking** |
| Raise or remove a `Decimal` field's `precision`, same `scale` | Safe (`field_precision_widened`) |
| Lower or add a `Decimal` field's `precision`, or change its `scale` | **Breaking** (`field_type_changed`) |
| Add a value type to a `Dict` or `List` field | **Breaking** (`field_type_changed`) |
| Change a `Dict` or `List` field's value type | **Breaking** (`field_type_changed`) |
| Remove a `Dict` or `List` field's value type | **Breaking** (`field_type_changed`) |
| Remove an element | **Breaking** |
| Add a new element | Safe |
| Visibility public to internal | **Breaking** |
| Visibility internal to public | Safe |
| Change `__type__` string | **Breaking** |
| Event version bump covered by a registered upcaster | Safe (mitigated) |
| Turn event sourcing on or off for an aggregate | **Breaking** (`event_sourcing_changed`) |
| Move an event-sourced aggregate's `stream_category` | **Breaking** (`stream_category_changed`) |
| Point an event-sourced aggregate's identity at another field | **Breaking** (`identity_field_changed`) |
| Drop an `@apply` handler while its event survives | **Breaking** (`apply_handler_removed`) |
| Drop a name from an event-sourced aggregate's `reserved` | **Breaking** (`reservation_removed`) |
| Add, remove or rename an event's field so that a field it keeps gets a different Protobuf field number, without a `__version__` bump | **Breaking** (`field_number_changed`). Protean numbers an event's Protobuf fields in sorted name order, and the numbers must not change within one `__version__`. To fix it, bump `__version__` and register an upcaster for the old version, which may return the payload unchanged. To land the change on purpose, see [Landing a deliberate breaking change](../../guides/compatibility-checking.md#landing-a-deliberate-breaking-change). |

Most of these rules apply to every persisted element: aggregates, entities,
value objects, commands, events, database models, and projections. Seven rows
are the exception. The five rows above the last one, and the `reserved`
field-removal row, read attributes only an aggregate has, so they are checked on
event-sourced aggregates and nowhere else. The last row, `field_number_changed`,
is checked on events only. The check runs whether or not the project generates
Protobuf schemas. A field added, removed or renamed on a command, aggregate,
entity, value object or projection can still move that element's Protobuf field
numbers, and the check does not report it.

### Decimal precision and scale

A `Decimal` field that stays `Decimal` is compared on its `precision` and
`scale`. A change from another type to `Decimal`, or back, is an ordinary
`field_type_changed`.

| From | To | Classification |
|------|----|----------------|
| `Decimal(precision=10, scale=2)` | `Decimal(precision=19, scale=2)` | Safe (`field_precision_widened`) |
| `Decimal(precision=10, scale=2)` | `Decimal(scale=2)` | Safe (`field_precision_widened`) |
| `Decimal(precision=19, scale=2)` | `Decimal(precision=10, scale=2)` | **Breaking** (`field_type_changed`) |
| `Decimal(scale=2)` | `Decimal(precision=19, scale=2)` | **Breaking** (`field_type_changed`) |
| `Decimal(precision=19, scale=2)` | `Decimal(precision=19, scale=4)` | **Breaking** (`field_type_changed`) |

Widening is safe because every old value still fits, both in a JSON payload and
in a wider `NUMERIC(p, s)` column. The same rules apply to a field renamed with
`renamed_from`: a widening rename reports both `field_renamed` and
`field_precision_widened`, and any other shape change reports only
`field_type_changed`.

The Avro verdict for `field_precision_widened` is `NONE`, even though the report
calls it safe. Avro matches two `decimal` types only when precision and scale
are both equal. A change of visibility from public to internal also gives
two different verdicts: the report calls it breaking, and the Avro verdict is
`FULL`.

### Dict and List value types

A `Dict` or `List` field that stays `Dict` or `List` is compared on its value
type, which the IR records as `content_type`. The check reports a breaking
change when that name differs. Adding or changing a value type means rows
stored before the change can fail to load. Removing one means a reader still on
the old code can reject rows written after it. Either way, old and new code no
longer accept the same rows.

| From | To | Classification |
|------|----|----------------|
| `Dict()` | `Dict(value_type=ValueObject(TierPrice))` | **Breaking** (`field_type_changed`) |
| `Dict(value_type=ValueObject(TierPrice))` | `Dict(value_type=ValueObject(Band))` | **Breaking** (`field_type_changed`) |
| `Dict(value_type=ValueObject(TierPrice))` | `Dict()` | **Breaking** (`field_type_changed`) |
| `List(content_type=String)` | `List(content_type=Integer)` | **Breaking** (`field_type_changed`) |

The message names both value types: "Field 'tier_prices' value type changed
from 'unset' to 'TierPrice'". An untyped `Dict()` records no value type and
shows as `unset`. An untyped `List()` records `Any` and shows as `Any`. When a
field renamed with `renamed_from` also changes its value type, the check
reports `field_type_changed` in place of `field_renamed`.

The check compares only the value type's name, so a change that keeps the name
is not reported. These changes give no entry:

- A value object swapped for another value object with the same class name
  from a different module.
- A change inside a nested or generic value type that keeps its outer name,
  such as `list[list[int]]` to `list[list[str]]`, `list[dict[str, int]]` to
  `list[dict[str, str]]`, or `Optional[int]` to `Optional[str]`.
- A change between two `choices` lists, which the IR records as `Literal`.

`Optional` and `Union` are different names, so a change between them is
breaking. Before Python 3.14, `Optional[int]` records `Optional` and
`Union[int, str]` records `Union`. A change from the first to the second means
a list that took `None` no longer does. Python 3.14 records `Optional[int]`
itself as `Union`, so a diff of an IR built on 3.13 against one built on 3.14
also reports the unchanged field. Build both IRs on the same Python version to
avoid it.

### Published event contracts

`diff_ir()` also checks every published event in its `contracts` section and
lists the breaks in `contracts.breaking_changes`. `diff_ir()` sets
`summary.has_breaking_changes` from that list. The published-contract check
applies the same field rules as the compatibility report: a field type change,
a `Dict` or `List` value type change, a breaking `Decimal` precision or scale
change, and a required field added without a default. So for a published
event's fields, the two lists flag the same field breaks, with these
exceptions:

- An event version bump covered by an upcaster: the report marks those field
  changes as mitigated, and the contract check does not.
- An event that becomes published in the same diff: the contract check compares
  only events published on both sides, so a field break in that diff is in the
  report alone.
- A field inside a value object the event holds: the report flags it on the
  value object, and the contract check compares only the event's own fields.
- `exclude` in `.protean/config.toml` filters the compatibility report only. A
  contract break on an excluded published event still counts as breaking.
  `protean ir diff` and the `protean-check-compat` hook still print it.
- A change that moves an event's Protobuf field number within one
  `__version__`: the report flags it as `field_number_changed` for every event,
  published or not, and the contract check has no matching entry.

The contract check writes these field entries. In the table, the List column
names the key under `contracts` that holds each entry:

| Entry `type` | List | When | Keys |
|--------------|------|------|------|
| `contract_field_type_changed` | `breaking_changes` | A field's type changes, a `Dict` or `List` field's value type changes, or a `Decimal` field's shape changes in a breaking way. A field renamed with `renamed_from` carries `renamed_to`; a field that keeps its name does not. | `fqn`, `field`, `left`, `right`, `message`, and `renamed_to` on a rename |
| `contract_required_field_added` | `breaking_changes` | A required field without a default is added | `fqn`, `field`, `message` |
| `contract_field_removed` | `breaking_changes` | A field is removed, no rename claims it, and the next row does not apply | `fqn`, `field`, `classification`, `message`, and `deprecated` when the field was deprecated |
| `contract_field_removed` | `expected_removals` | A deprecated field is removed at or after its removal version, and the caller passed `current_version` to `diff_ir()`. This is not a break. `protean ir diff` and the `protean-check-compat` hook do not pass `current_version`, so there the removal is a `premature_removal` in `breaking_changes`. | `fqn`, `field`, `classification` (always `expected_removal`), `deprecated`, `message` |
| `contract_field_renamed` | `renamed_fields` | A plain rename: a field with `renamed_from` and no type change, value type change or breaking `Decimal` shape change. This is not a break. | `fqn`, `field`, `renamed_to`, `message` |

`protean ir diff` prints the report's breaking changes and
`contracts.breaking_changes` under "Breaking Changes". When the report and
`contracts.breaking_changes` hold the same break (the same event, the same
field, and the same kind of change), `protean ir diff` prints it once, with the
contract message.

### Replay hazards on an event-sourced aggregate

An event-sourced aggregate's authoritative state is a stream of events, rebuilt
by reading that stream and applying the events in it. Protean may store a
snapshot of serialized aggregate state alongside the stream. The snapshot is a
rebuildable cache: when a snapshot no longer constructs, Protean discards it
and replays the stream instead. So the checker reports the changes that stop
Protean from rebuilding the aggregate from its stream, even when the
aggregate's fields stay the same.

The stream an aggregate reads is named `f"{stream_category}-{identifier}"`, so
moving the stream category leaves the whole history under the old name. For the
same reason, pointing the identity at another field makes the aggregate read a
stream keyed by a value no writer ever used. Either way a load of an existing
aggregate finds nothing. Turning event sourcing on or off changes where state
lives, and the old state cannot be read the new way. Dropping an `@apply`
handler while its event survives leaves historical events of that type with
nothing to apply them, and the rebuild raises. Dropping a name from `reserved`
makes the earlier removal of that field breaking again. Replay then stops
dropping an assignment to the name and a call to its `add_<name>` or
`remove_<name>` helper, so a retained handler that still makes either call
raises again.

Some related cases are already covered by the general rules above and are not
reported again here: a change to the identity field's *type* is a
`field_type_changed`, and an event removed from the domain outright is an
`element_removed` on that event. Deleting an event class and its `@apply`
method together is one act, so it reports once, as the removal.

### Evolution-aware classification

The checker understands three evolution mechanisms:

- **Reserved field on an event-sourced aggregate**: Removing a field from an
  event-sourced aggregate is safe only when the aggregate declares the field name
  in `reserved`. The `reserved` declaration does the migration: during
  replay, Protean drops an assignment to a reserved name (from a retained
  `@apply` handler for a retired event) instead of raising, so the aggregate
  still rebuilds. Protean also drops a call to the `add_<name>` or
  `remove_<name>` helper of a removed association, so the child entities that
  call would have added are not rebuilt. `get_one_from_<name>` and
  `filter_<name>` still raise. The safe rating assumes the retained handlers
  only write the removed name: a handler that reads the removed collection
  still breaks replay, and a handler that builds a child entity needs that
  entity class to stay in the domain. The checker rates only the aggregate's
  own field removal safe this way, and only when the aggregate is event-sourced
  on both sides of the diff. A type change or a newly required field stays
  breaking, because a stored snapshot can survive a type change and skip
  replay, and replay runs no required-field check. The checker still reports
  the [replay hazards](#replay-hazards-on-an-event-sourced-aggregate) above on
  their own. Reusing a reserved name for a live field raises at registration.
- **Deprecation grace**: A field marked `deprecated` and removed at or past its
  `removal` version is an *expected removal* (safe), not a breaking one. This
  applies to every persisted element, including internal and event-sourced
  events (not only published event contracts). The checker compares the
  `removal` version against the release version. The `protean ir diff` CLI does
  not yet supply a release version, so this downgrade applies when the diff is
  run with an explicit current version. Write the `removal` version as a
  string, such as `"0.20"`, because a number loses its trailing zeros.
  `deprecated=` refuses a number when the element or field is declared. The
  diff checks every `deprecated` block in both IR files before comparing them.
  When a hand-written file holds a malformed block, such as a version written
  as a number, the diff raises `ConfigurationError` naming the element or
  field. `protean ir diff` then prints the error on stderr and exits 2.
- **Upcaster mitigation**: When an event's `__version__` bumps and a registered
  [upcaster](../../patterns/event-versioning-and-evolution.md) chain covers the
  old→new version path, the schema-transformation changes that make up that
  bump, field removals, type changes, required-field additions, and the `__type__`
  version-string change, are downgraded from breaking to safe, each citing the
  mitigating upcaster. Two cases stay breaking: an unrelated change made in the
  same bump (for example a public→internal visibility flip), and a version bump
  with an upcaster *gap* (a prior version with no path to the new one).

---

## Three-tier breaking change taxonomy

Protean follows a tiered approach to breaking changes (see
[ADR-0004](../../adr/0004-release-workflow-and-breaking-change-policy.md)
for the full rationale):

### Tier 1: Surface breaks

Renamed classes, moved imports, changed signatures.

**Mitigation:** Introduce the new API alongside the old. The old API emits
`DeprecationWarning` with a specific removal version and delegates to the
new implementation. Keep the old API for at least **2 minor versions**.

```python
--8<-- "reference/compatibility/001.py:old_method"
```

### Tier 2: Behavioral breaks

Same signature, different behavior.

**Mitigation:** Introduce new behavior behind a configuration flag,
defaulting to old behavior. Keep the old behavior available for at least **3
minor versions**.

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
   not trigger breaking change alerts during its deprecation period. On a
   published event, `exclude` does not cover the contract breaks; see
   [Published event contracts](#published-event-contracts).
4. **Remove** in a later release, once the declared removal version has
   arrived and has been announced.

The `protean ir diff` command distinguishes expected removals (deprecated
elements past their removal version) from unexpected removals.

Events additionally accept a `superseded_by` option naming the replacement (an
Event class or a name string):

```python
--8<-- "reference/compatibility/002.py:setup"
--8<-- "reference/compatibility/002.py:superseded_by"
```

Protean surfaces the successor two ways. Raising a deprecated event emits a
`ProteanDeprecationWarning` (once per event type) that names the successor, and
the `DEPRECATED_ELEMENT` diagnostic appends `superseded by \`<name>\``. The
warning names an Event class by its class name (`OrderPlacedV2`). The
diagnostic names it by its fully qualified name
(`ordering.events.OrderPlacedV2` for a class defined in `ordering/events.py`).
The successor is for documentation only and is never resolved to a link.

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
| `strictness` | string | `"strict"` | `"strict"` exits non-zero on breaking changes. `"warn"` reports but allows. `"off"` skips the comparison: `ir diff` still checks its options and loads both sides, exits 2 if either step fails, then exits 0. |
| `exclude` | list of strings | `[]` | Fully-qualified names of elements to leave out of the compatibility report. A published event's contract breaks are still checked; see [Published event contracts](#published-event-contracts). |

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
