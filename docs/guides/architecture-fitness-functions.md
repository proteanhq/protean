# Architecture fitness functions

Architecture fitness functions are automated, objective, repeatable checks that
enforce your architectural decisions on every commit. Protean runs them with
`protean check`: it builds your domain's
[Intermediate Representation (IR)](compose-a-domain/inspecting-the-ir.md) — the
complete structural snapshot of the domain — and reports every place the model
drifts from sound Domain-Driven Design.

This guide covers running the checks, tuning severity, suppressing findings
during gradual adoption, wiring them into CI, and writing your own rules. For
the full list of rules see the [Fitness Function Catalog](../reference/fitness-functions.md);
for the CLI flags and output schema see the
[`protean check` reference](../reference/cli/check.md).

---

## What are architecture fitness functions?

DDD makes structural promises: aggregates are consistency boundaries that
reference each other by identity, events are past-tense facts, every command has
a handler, bounded contexts don't import each other's infrastructure. These are
easy to state and easy to erode as a codebase grows.

Because Protean holds the whole domain as an IR, many of these promises are
*decidable* — they can be checked mechanically at build time, with no runtime and
no database. `protean check` walks the IR and emits a **diagnostic** for each
violation, each carrying a rule `code`, a `category`, a severity `level`, the
offending `element`, the reason it fired (`rule.rationale`), and how to fix it
(`rule.fix`).

The checks are deterministic: the same domain always produces the same findings
in the same order. That makes them safe to gate CI on.

---

## Running `protean check`

```bash
# Check the domain discovered from the current directory
protean check

# Check an explicit domain module
protean check --domain=my_app.domain

# Show only warnings and errors (hide info-level advice)
protean check --level=warning

# One-line summary for scripts
protean check --quiet
```

`protean check` prints a human-readable report by default. The `--level` flag
filters what is *displayed* — it never changes the exit code. See
[Strictness and CI gating](#strictness-and-ci-gating) below for how the exit code
is actually decided.

---

## Built-in rules

`protean check` ships the following rules, grouped by category. Each links to its
full entry — rationale, fix, and configuration — in the
[catalog](../reference/fitness-functions.md).

### Aggregate design

| Code | Level | Flags |
|------|-------|-------|
| [`CROSS_AGGREGATE_REFERENCE`](../reference/fitness-functions.md#cross-aggregate-reference) | warning | A `Reference` to another aggregate's root (violates Vernon's Rule 3). |
| [`ES_AGGREGATE_NO_EVENTS`](../reference/fitness-functions.md#es-aggregate-no-events) | warning | Event-sourced aggregate with no events registered. |
| [`VALUE_OBJECT_MUTABLE_FIELD`](../reference/fitness-functions.md#value-object-mutable-field) | warning | Value object with a `List`/`Dict` field (breaks immutability). |
| [`AGGREGATE_TOO_LARGE`](../reference/fitness-functions.md#aggregate-too-large) | info | Aggregate exceeding `[lint].aggregate_size_limit` entities. |
| [`HANDLER_TOO_BROAD`](../reference/fitness-functions.md#handler-too-broad) | info | Handler exceeding `[lint].handler_breadth_limit` message types. |
| [`EVENT_WITHOUT_DATA`](../reference/fitness-functions.md#event-without-data) | info | Event with no fields. |
| [`AGGREGATE_NO_INVARIANTS`](../reference/fitness-functions.md#aggregate-no-invariants) | info | Aggregate with no pre/post invariants. |

### Bounded context

| Code | Level | Flags |
|------|-------|-------|
| [`CIRCULAR_CLUSTER_DEPENDENCY`](../reference/fitness-functions.md#circular-cluster-dependency) | warning | Circular identity references between aggregate clusters. |
| [`INFRA_IMPORT_IN_DOMAIN`](../reference/fitness-functions.md#infra-import-in-domain) | warning (opt-in) | Domain element importing from `protean.adapters`. |

### Handler completeness

| Code | Level | Flags |
|------|-------|-------|
| [`UNHANDLED_EVENT`](../reference/fitness-functions.md#unhandled-event) | warning | Event with no registered consumer. |
| [`UNUSED_COMMAND`](../reference/fitness-functions.md#unused-command) | warning | Command with no handler. |
| [`ES_EVENT_MISSING_APPLY`](../reference/fitness-functions.md#es-event-missing-apply) | warning | Event-sourced event with no `@apply` handler. |
| [`PUBLISHED_NO_EXTERNAL_BROKER`](../reference/fitness-functions.md#published-no-external-broker) | warning | `published=True` event but no external broker configured. |
| [`AGGREGATE_WITHOUT_COMMAND_HANDLER`](../reference/fitness-functions.md#aggregate-without-command-handler) | warning | Aggregate with no write path. |
| [`PROJECTION_WITHOUT_PROJECTOR`](../reference/fitness-functions.md#projection-without-projector) | warning | Projection that nothing populates. |
| [`QUERY_HANDLER_WITHOUT_QUERY`](../reference/fitness-functions.md#query-handler-without-query) | warning | Query handler with no query registered. |
| [`PROJECTOR_HANDLES_ORPHANED_EVENT`](../reference/fitness-functions.md#projector-handles-orphaned-event) | warning | Projector handling an unregistered event. |
| [`COMMAND_HANDLER_CROSS_CLUSTER`](../reference/fitness-functions.md#command-handler-cross-cluster) | warning | Command handler for another cluster's command. |
| [`EVENT_HANDLER_FOREIGN_EVENT`](../reference/fitness-functions.md#event-handler-foreign-event) | warning | Event handler reacting to another cluster's event. |
| [`SUBSCRIBER_NO_STREAMS`](../reference/fitness-functions.md#subscriber-no-streams) | info | Subscriber with no stream configured. |
| [`PROCESS_MANAGER_UNCLOSED`](../reference/fitness-functions.md#process-manager-unclosed) | info | Process manager with no `end=True` handler. |

### Naming conventions

| Code | Level | Flags |
|------|-------|-------|
| [`EVENT_NOT_PAST_TENSE`](../reference/fitness-functions.md#event-not-past-tense) | info | Event name is not past tense. |
| [`COMMAND_NOT_IMPERATIVE`](../reference/fitness-functions.md#command-not-imperative) | info | Command name is not verb-first imperative. |
| [`AGGREGATE_NOT_NOUN`](../reference/fitness-functions.md#aggregate-not-noun) | info | Aggregate name reads as a process, not a noun. |

### Persistence, versioning, and deprecation

| Code | Level | Flags |
|------|-------|-------|
| [`UNBOUNDED_INDEXED_STRING`](../reference/fitness-functions.md#unbounded-indexed-string) | warning | An index over an unbounded string field. |
| [`UPCASTER_GAP`](../reference/fitness-functions.md#upcaster-gap) | warning | Stored event version with no upcaster path. |
| [`DEPRECATED_ELEMENT`](../reference/fitness-functions.md#deprecated-element) | info | Element scheduled for removal. |
| [`DEPRECATED_FIELD`](../reference/fitness-functions.md#deprecated-field) | info | Field scheduled for removal. |
| [`DEPRECATED_OPTION`](../reference/fitness-functions.md#deprecated-option) | warning or info | Deprecated option or alias. |
| [`DEPRECATED_EMAIL`](../reference/fitness-functions.md#deprecated-email) | info | Deprecated email subsystem. |

---

## The suppression system

Real domains adopt these checks gradually. Protean gives you two suppression
layers, applied in this order.

### Element-level: `suppress_checks`

Silence specific codes for a single element with the `suppress_checks` option on
its decorator. This is the right tool when a violation is a deliberate,
documented exception for that element:

```python
@domain.aggregate(
    indexes=[Index("body")],
    suppress_checks=["UNBOUNDED_INDEXED_STRING"],
)
class Note:
    body = Text()
```

`suppress_checks` accepts a list of rule codes (a bare string is treated as a
single code). It is available on every domain element decorator — aggregates,
entities, value objects, events, commands, handlers, projections, and so on.

### Config-level: `[lint].suppressions`

For gradual remediation across the whole domain, the `[lint].suppressions`
allow-list *grandfathers* the first `N` findings of a code — you adopt a rule
without failing CI on pre-existing violations, while any *new* violation beyond
`N` still surfaces:

```toml
[lint.suppressions]
UNHANDLED_EVENT = 3          # grandfather the first 3 findings; a 4th fails CI
```

Findings are sorted into a deterministic `(code, element, field, message)` order
before the first `N` are dropped, so the same domain always suppresses the same
findings.

### Which layer to use

| You want to… | Use |
|--------------|-----|
| Permanently exempt one element for a documented reason | `suppress_checks` on that element |
| Adopt a rule on a legacy domain without fixing everything at once | `[lint].suppressions` allow-list, then drive the count to zero |

Per-element `suppress_checks` takes precedence over the config allow-list.

!!! note "There is no global disable"

    Protean has no `disabled_rules` config key and no `--save-baseline` flag.
    The two layers above are the supported way to silence findings; the
    allow-list is the gradual-adoption path a baseline would otherwise serve.
    Two `info` rules are threshold-tunable
    (`[lint].aggregate_size_limit`, `[lint].handler_breadth_limit`) and
    `INFRA_IMPORT_IN_DOMAIN` is opt-in
    (`[lint].check_infra_imports`).

---

## Strictness and CI gating

Severity has two independent knobs — do not confuse them:

- **`--level`** (CLI, default `info`) filters what is *displayed*. It never
  changes the exit code and never filters the machine formats.
- **`[lint].level`** (config, default `warn`) is the *severity floor* that
  decides the exit code — this is what gates CI.

```toml
[lint]
level = "warn"        # errors + warnings gate CI (default)
```

| `[lint].level` | Exit `0` unless… |
|----------------|------------------|
| `error` | there is a validator error. |
| `warn` (default) | there is an error or a warning. |
| `info` | there is an error, warning, or info finding. |

Exit codes: `1` on any validator error (always), `2` on a gating finding at or
above the floor, `0` otherwise. Set `level = "error"` while you burn down
warnings, then tighten to `warn` once the domain is clean.

---

## CI integration

`protean check` speaks two machine formats. Both emit the **unfiltered** set of
findings regardless of `--level`.

### SARIF → GitHub Code Scanning

`--format=sarif` emits [SARIF 2.1.0](https://sarifweb.azurewebsites.net/), which
GitHub Code Scanning renders as inline PR annotations and a security dashboard:

```yaml
# .github/workflows/fitness.yml
name: Architecture fitness
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install protean
      - run: protean check --domain=my_app.domain --format=sarif > protean.sarif
        continue-on-error: true      # upload even when findings gate the build
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: protean.sarif
```

Each SARIF result carries the rule's rationale and fix, and a `helpUri` back to
this documentation.

### GitHub Actions annotations

For a simpler pipeline without Code Scanning, `--format=github-annotations`
emits `::error`/`::warning`/`::notice` workflow commands that appear inline on
the run:

```yaml
      - run: protean check --domain=my_app.domain --format=github-annotations
```

---

## Writing custom rules

Register additional rules with the `[lint].rules` config key — a list of dotted
import paths to callables with the signature `(ir: dict) -> list[dict]`:

```toml
[lint]
rules = ["my_app.lint.check_naming"]
```

```python
# my_app/lint.py
def check_naming(ir: dict) -> list[dict]:
    """Flag aggregates whose short name is not PascalCase."""
    findings = []
    # ir["elements"] is a flat index of element type -> list of FQNs.
    for fqn in ir.get("elements", {}).get("AGGREGATE", []):
        name = fqn.rsplit(".", 1)[-1]
        if not (name[:1].isupper() and name.isalnum()):
            findings.append({
                "code": "AGGREGATE_NOT_PASCAL_CASE",
                "element": fqn,
                "level": "info",
                "message": f"{name} should be PascalCase",
            })
    return findings
```

The `ir` argument is the full IR document — see the
[IR specification](../concepts/internals/ir-specification.md) for its structure.
A custom finding requires `code`, `element`, `level` (`warning` or `info`), and
`message`; `category` defaults to `custom`, and `rule`/`suggestion` are optional.
A rule that raises, returns a non-list, or returns a finding missing a required
key is logged and skipped — it never crashes `protean check`. Custom findings
pass through the same suppression and gating machinery as built-in rules.

---

## Pre-commit integration

Run `protean check` locally on every commit alongside the
[IR compatibility hooks](compatibility-checking.md#step-3-add-pre-commit-hooks).
The pre-commit hook wiring is documented in the
[compatibility-checking guide](compatibility-checking.md); point the hook at
`protean check` to fail commits that introduce new violations.

---

## Related

- [Fitness Function Catalog](../reference/fitness-functions.md) — every rule in detail.
- [`protean check` reference](../reference/cli/check.md) — flags, formats, exit codes, JSON schema.
- [`[lint]` configuration](../reference/configuration/index.md#lint) — config keys.
- [Compatibility checking](compatibility-checking.md) — the complementary IR-diff breaking-change checks.
