# Compatibility Reference

Reference documentation for Protean's IR compatibility checking system --
the rules that classify changes as safe or breaking, the three-tier
taxonomy, and the deprecation lifecycle.

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
| Change field type | **Breaking** |
| Remove an element | **Breaking** |
| Add a new element | Safe |
| Visibility public to internal | **Breaking** |
| Visibility internal to public | Safe |
| Change `__type__` string | **Breaking** |

These rules apply to all persisted elements: aggregates, entities, value
objects, commands, events, database models, and projections.

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
4. **Remove** in a cleanup release after the survival window.

The `protean ir diff` command distinguishes expected removals (deprecated
elements past their removal version) from unexpected removals.

---

## `.protean/config.toml` reference

All settings are optional -- sensible defaults apply when the file is
absent.

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

Maps logical domain names to their module paths. When present, pre-commit
hooks iterate over all configured domains automatically -- no `--domain`
argument needed. Each domain's IR is stored under `.protean/<name>/ir.json`.

| Key | Type | Description |
|-----|------|-------------|
| `<name>` | string | Dotted module path to the domain (e.g. `"identity.domain"`). The key is the logical name used as the subdirectory. |
