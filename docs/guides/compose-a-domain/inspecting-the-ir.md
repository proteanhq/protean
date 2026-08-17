# Inspecting the IR

After you define and initialize a domain, Protean can generate its
**Intermediate Representation (IR)**, a JSON document that captures the
complete topology of your domain model: what elements exist, what shape they
have, and how they connect.

The IR is useful for:

- **Reviewing** your domain structure at a glance
- **Diffing** changes between versions in source control
- **Feeding** downstream tools (documentation generators, diagram builders,
  contract validators)
- **Debugging** wiring issues (missing handlers, orphaned events)

---

## Generate the IR in code

Call `domain.to_ir()` on an initialized domain to get a Python dict:

```python
from protean import Domain

domain = Domain(__name__)

# ... register aggregates, commands, events, handlers ...

domain.init()

ir = domain.to_ir()
```

The returned dict contains the full IR. You can serialize it to JSON:

```python
import json

print(json.dumps(ir, indent=2))
```

Or write it to a file for version control:

```python
from pathlib import Path

Path("domain-ir.json").write_text(
    json.dumps(ir, indent=2, sort_keys=True)
)
```

---

## Generate the IR from the CLI

The `protean ir show` command generates the IR without writing Python:

```bash
# Full JSON output
protean ir show --domain=my_app.domain

# Human-readable summary with element counts
protean ir show --domain=my_app.domain --format=summary
```

See the [CLI reference](../../reference/cli/ir.md) for all options.

---

## Top-level structure

Every IR document has the same shape:

```json
{
  "$schema": "https://protean.dev/ir/v0.2.0/schema.json",
  "ir_version": "0.2.0",
  "generated_at": "2026-03-01T12:00:00Z",
  "checksum": "sha256:a1b2c3...",

  "domain": { },
  "clusters": { },
  "projections": { },
  "flows": { },
  "elements": { },
  "diagnostics": [ ]
}
```

| Section | What it contains |
|---------|-----------------|
| `domain` | Bounded context name and global config (identity strategy, processing mode) |
| `clusters` | Aggregate clusters, each aggregate with its entities, value objects, commands, events, handlers, and repositories |
| `projections` | Read-side projections with their projectors, queries, and query handlers |
| `flows` | Cross-aggregate elements: domain services, process managers, subscribers |
| `elements` | Flat index of all element types for quick lookup |
| `diagnostics` | Warnings like unhandled events (informational, does not affect validity) |

---

## Behavioral edges (`method_edges`)

Alongside its structure, the IR records what causes what. An element that owns
methods can carry a `method_edges` map, keyed by method name:

```json
"method_edges": {
  "place_order": { "raises": ["ecommerce.ordering.OrderPlaced"] },
  "handle_place_order": {
    "invokes": [{ "element": "ecommerce.ordering.Order", "method": "place_order" }]
  }
}
```

- **`raises`** appears on aggregates and entities. It lists the events a method
  raises, derived by co-location: every event built in a method that also calls
  `raise_`. It can over-report (a method that builds two events and raises one
  records both) and under-report (an event built in a helper and raised through
  it is missed).
- **`invokes`** appears on command handlers, event handlers, projectors, and
  process managers. It lists the element methods a handler method calls, matched
  by name against the methods in scope. The match is receiver-blind: a name
  shared by more than one method in scope is skipped (so an edge can be
  missing), and a unique name is recorded even when the real receiver is
  something else (so an edge can be wrong). A projector or process manager is
  scoped to aggregate and entity method names, so it rarely carries a real edge.

Both edges are read from the source as written, not proven, so treat them as a
guide to the domain's behavior. A method with no edge is absent, and an element
with no edged method carries no `method_edges` key.

---

## Determinism and diffing

The same domain always produces **byte-identical** IR JSON (excluding the
`generated_at` timestamp). Keys are sorted alphabetically at every level,
lists are sorted, and optional attributes with default values are omitted.

This makes the IR safe to commit to source control and diff across versions.
The `checksum` field (SHA-256 of the canonical JSON) provides a quick staleness
check. If the checksum hasn't changed, the domain structure hasn't changed.

See the [Compatibility Checking](../compatibility-checking.md) guide for
how to use IR diffing, pre-commit hooks, and CI integration to detect
breaking changes automatically.

---

## The `$schema` URI

The `$schema` field contains a logical URI
(`https://protean.dev/ir/v0.2.0/schema.json`). This URI identifies the
schema version but is **not a network endpoint**, the actual JSON Schema ships
with the Protean package at `protean.ir.SCHEMA_PATH`.

To validate an IR document programmatically:

```python
from jsonschema import validate
from protean.ir import load_schema

schema = load_schema()
validate(instance=ir, schema=schema)
```

---

## Compatibility contract for tool authors

If you are building tools that consume IR documents, follow these rules to
ensure forward compatibility:

**Ignore unknown keys.** Every object in the IR may gain new keys in future
minor versions. Your tool must skip keys it does not recognize rather than
failing. This is the single most important rule for IR consumers.

**Do not rely on key ordering.** Keys are sorted for determinism, but your
code should not depend on iteration order for correctness.

**Provide defaults for missing optional keys.** Optional attributes (like
`description` on elements or `via` on association fields) may be absent.
Treat missing keys as their default value.

**Check `ir_version`.** Reject documents whose major version is higher than
what your tool supports. Minor version increases are always backward
compatible. New keys may appear, but existing keys retain their meaning.

See the [IR specification](../../concepts/internals/ir-specification.md) for
the full compatibility contract, field reference, and design decisions.

---

## From IR to JSON Schema

Once you have an IR document, you can generate **JSON Schema (Draft 2020-12)**
files for every data-carrying element, aggregates, entities, value objects,
commands, events, and projections. This is useful for contract validation,
documentation, and integration with external tools.

See the [Schema Generation guide](schema-generation.md) for details, or use
the CLI directly:

```bash
protean schema generate --domain=my_app.domain
protean schema show OrderPlaced --domain=my_app.domain
```
