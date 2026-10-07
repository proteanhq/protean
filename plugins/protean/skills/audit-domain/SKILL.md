---
name: audit-domain
description: >
  Run a comprehensive design-quality audit on a Protean domain codebase. Scans for anti-patterns,
  modeling smells, and convention violations — then produces a prioritized report with links to
  refactoring skills. Use when the user says "audit my domain", "check domain quality",
  "find anti-patterns", "review my code", "domain health check", "what should I refactor",
  "code review my domain", "find design issues", or when onboarding to an unfamiliar Protean codebase
  and wanting a quick quality assessment.
license: Apache-2.0
compatibility: "Requires Python 3.11+, protean framework"
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [aggregate, command-handler, event-handler, value-object, repository]
  diagnostic_codes:
    - AGGREGATE_NO_INVARIANTS
    - AGGREGATE_TOO_LARGE
    - AGGREGATE_WITHOUT_COMMAND_HANDLER
    - COMMAND_HANDLER_CROSS_CLUSTER
    - CROSS_AGGREGATE_REFERENCE
    - EVENT_HANDLER_FOREIGN_EVENT
    - HANDLER_PERSISTS_AND_CALLS_OUT
    - HANDLER_TOO_BROAD
---

# Audit Domain

Scan a Protean domain codebase for design-quality issues, anti-patterns, and convention violations.
Produces a prioritized report linking each finding to the appropriate refactoring skill.

## What this produces

| Output | Purpose |
|--------|---------|
| **Finding list** | Each anti-pattern found, classified by severity and category |
| **Prioritized report** | Findings grouped by severity (CRITICAL > HIGH > MEDIUM > LOW) |
| **Refactoring links** | Each finding links to the skill that fixes it |
| **Summary statistics** | Aggregate counts, handler counts, issue breakdown |

## Start with `protean check`

`protean check` finds part of what this audit looks for. Run it first and record what it reports:

```bash
protean check --domain=<module>
```

If the module defines more than one domain, name the one to audit after a colon, for example `--domain=myapp.domain:billing`.

Through the MCP server, call the `check` tool instead. Do not pass `--level=warning` here. Several of the codes below are info level, and `--level=warning` would hide them.

| Code | Level | What it reports | Severity | Fix |
|------|-------|-----------------|----------|-----|
| `COMMAND_HANDLER_CROSS_CLUSTER` | warning | A command handler processes another cluster's command | HIGH | [command-handler](../command-handler/SKILL.md) |
| `CROSS_AGGREGATE_REFERENCE` | warning | A field holds a `Reference` to another aggregate root | HIGH | [split-aggregate](../split-aggregate/SKILL.md) |
| `EVENT_HANDLER_FOREIGN_EVENT` | warning | An event handler reacts to another cluster's event | MEDIUM | [event-handler](../event-handler/SKILL.md) |
| `AGGREGATE_TOO_LARGE` | info | The aggregate's cluster has more child entities than `[lint] aggregate_size_limit` (default 5) | MEDIUM, or HIGH with the category 4 signals | [split-aggregate](../split-aggregate/SKILL.md) |
| `HANDLER_PERSISTS_AND_CALLS_OUT` | info | A handler method persists and then calls an external system while the transaction is open | MEDIUM | [command-handler](../command-handler/SKILL.md) |
| `AGGREGATE_NO_INVARIANTS` | info | The aggregate declares no invariant | LOW | [add-validation](../add-validation/SKILL.md) |
| `HANDLER_TOO_BROAD` | info | A command or event handler handles more message types than `[lint] handler_breadth_limit` (default 5) | LOW | [command-handler](../command-handler/SKILL.md), [event-handler](../event-handler/SKILL.md) |

Report each of these codes at the severity in the table. `check` prints other diagnostics too, such as errors and naming and wiring codes. Report those at their level: an error as CRITICAL, a warning as MEDIUM, and an info diagnostic as LOW. The element skills cover their fixes.

## Detection categories

`check` has no rule for most of these categories, and it does not look at endpoints or tests, so they need a reading of the code. Scan for them in order. Each has a detection heuristic and a linked fix. Where a finding is one `check` already reported, record it once, with its code.

### 1. Logic leak — business logic outside aggregates

**Detect**: Handler methods (`@handle`) with more than ~5 lines of logic beyond load/persist.
Look for conditionals, calculations, state checks, or validation in handlers, services, or endpoints.

**Signals**:
- `if` statements in handler methods (beyond simple error checks)
- Arithmetic or string operations in handlers
- Multiple attribute assignments on an aggregate from inside a handler
- `raise ValidationError` or `raise ValueError` in handlers or endpoints

**Severity**: HIGH
**Fix**: [refactor-move-logic-to-aggregate](../refactor-move-logic-to-aggregate/SKILL.md)

### 2. Primitive obsession — missing value objects

**Detect**: Groups of fields that always appear together, or bare `String`/`Float`/`Integer`
fields representing domain concepts that deserve their own type.

**Signals**:
- Field groups: `amount` + `currency`, `street` + `city` + `zip_code` + `state`
- Fields with `_email`, `_phone`, `_url` suffixes
- `Float` fields representing money
- `String` fields with validators that could be a VO (email, phone, URL patterns)
- Same field group repeated across multiple aggregates/entities

**Severity**: MEDIUM
**Fix**: [refactor-extract-value-object](../refactor-extract-value-object/SKILL.md)

### 3. Transaction boundary violation — multiple aggregates per handler

**Detect**: Handler methods that call `repository.add()` or `domain.repository_for()` for
more than one aggregate class.

**Signals**:
- `current_domain.repository_for(X).add()` calls on more than one aggregate type
- Multiple `domain.repository_for(X)` calls in one handler
- Loading and mutating a second aggregate inside a handler

**Severity**: CRITICAL
**Fix**: [refactor-introduce-events](../refactor-introduce-events/SKILL.md)

### 4. God aggregate — oversized aggregate root

**Detect**: `check` reports `AGGREGATE_TOO_LARGE` when the aggregate's cluster holds more child entities than `[lint] aggregate_size_limit` (default 5). That is the only size rule the framework enforces.

**Signals this skill adds** (`check` does not count these, so judge them by reading the aggregate):
- More than 12-15 fields on a single aggregate
- More than 8-10 public methods
- More than 5 invariants
- Unrelated groups of fields (e.g., order fields + shipping fields + payment fields)
- Multiple `HasMany` associations pointing to unrelated entity types

**Severity**: HIGH
**Fix**: [split-aggregate](../split-aggregate/SKILL.md)

### 5. Manual UoW wrapping

**Detect**: `with UnitOfWork()` or `from protean import UnitOfWork` inside handler code.

**Signals**:
- `UnitOfWork` import in handler files
- `with UnitOfWork():` blocks inside `@handle` methods

**Severity**: MEDIUM
**Fix**: Remove the wrapping — handlers run in an implicit UoW automatically.

### 6. Direct handler invocation

**Detect**: Calling handler methods directly instead of using `domain.process()`.

**Signals**:
- `handler = SomeHandler()` followed by `handler.method(command)`
- Importing handler classes in API endpoints or other handlers
- Missing `domain.process()` or `current_domain.process()` calls

**Severity**: HIGH
**Fix**: Replace with `domain.process(command)`.

### 7. Scattered validation

**Detect**: Validation logic outside the domain layer — in handlers, endpoints, or services.

**Signals**:
- `raise ValidationError` in handler methods
- Input checking `if not field:` in API endpoints
- Duplicate validation (same check in endpoint AND aggregate)
- Missing `@invariant.post` decorators on aggregates with complex rules

**Severity**: MEDIUM
**Fix**: [add-validation](../add-validation/SKILL.md)

### 8. Circular import risk — class references in DTOs

**Detect**: Commands, events, entities, or value objects using class references for `part_of`
instead of string references.

**Signals**:
- `@domain.command(part_of=OrderAggregate)` (a class reference where a string would do)
- `@domain.event(part_of=Order)` where `Order` is imported at top of file
- `from .order import Order` in command/event files

**Severity**: LOW
**Fix**: Change to string references: `part_of="Order"`.

### 9. Mock overuse in tests

**Detect**: Tests using `Mock()`, `MagicMock()`, or `@patch` for domain elements.

**Signals**:
- `from unittest.mock import Mock, patch, MagicMock`
- `mock_repo = Mock()` or `@patch("...repository...")`
- Mocked domain objects instead of real in-memory ones

**Severity**: MEDIUM
**Fix**: Replace with Protean's in-memory adapters and real domain objects.

### 10. Missing event versioning

**Detect**: Events without `__version__` attribute, especially in production codebases.

**Signals**:
- `@domain.event` classes without `__version__`
- Events that have been modified (fields added/removed) without version bump
- Missing upcasters for versioned events

**Severity**: LOW (new projects), HIGH (production with event store)
**Fix**: Add `__version__` to all events; create upcasters for schema changes.

### 11. Missing events — synchronous cross-aggregate calls

**Detect**: Aggregate methods or handlers that directly call into another aggregate's
logic without raising events.

**Signals**:
- Handler loading two different aggregate types and mutating both
- Aggregate method calling `domain.repository_for(OtherAggregate)`
- Service methods that orchestrate multiple aggregates without events

**Severity**: HIGH
**Fix**: [refactor-introduce-events](../refactor-introduce-events/SKILL.md)

## Process

### Step 1: Run `protean check`

Run `protean check --domain=<module>` (or `--domain=<module>:<name>` when the module defines more than one domain), or the MCP `check` tool, as described in [Start with `protean check`](#start-with-protean-check). Keep its output. Each code it reports is a finding, and the codes tell you which categories are already covered.

### Step 2: Discover domain files

Find all Python files containing `@domain.` decorators or importing from `protean`:

```
src/**/
├── **/aggregate*.py, **/model*.py
├── **/command*.py, **/event*.py
├── **/handler*.py, **/*_handler.py
├── **/service*.py
├── **/api*.py, **/*_api.py
└── **/test_*.py
```

### Step 3: Scan each file

For every domain file, check all 11 detection categories. Skip a finding `check` already reported in Step 1. Record each finding with:
- **File and line number**
- **Category** (1-11 from above), and the `check` code if there is one
- **Severity** (CRITICAL / HIGH / MEDIUM / LOW)
- **Description** — what was found
- **Suggestion** — one-sentence fix

### Step 4: Produce the report

```markdown
## Domain Audit Report

### Summary
- Files scanned: N
- Aggregates found: N
- Handlers found: N
- Issues found: N (C critical, H high, M medium, L low)
- From `check`: N (list the codes)

### CRITICAL
1. **[Category]: [description]** — `file.py:line`
   Fix: [one-sentence suggestion] → [link to skill]

### HIGH
1. ...

### MEDIUM
1. ...

### LOW
1. ...

### Recommended refactoring order
1. [Most impactful fix first]
2. [Second most impactful]
3. ...
```

### Step 5: Suggest refactoring order

Prioritize fixes by:
1. **CRITICAL first** — transaction boundary violations break data consistency
2. **HIGH next** — logic leaks and god aggregates compound over time
3. **MEDIUM** — primitive obsession and scattered validation are code smells
4. **LOW** — import style and versioning are hygiene items

## Common mistakes

1. **Reporting framework internals as issues** — Don't flag Protean's own patterns (like `_version`, `_events`, `meta_` attributes)
2. **Over-reporting field counts** — An aggregate with 12 fields isn't automatically a god aggregate if the fields are cohesive
3. **Ignoring context** — A handler with 8 lines might be fine if it's orchestrating a complex but legitimate single-aggregate flow
4. **Missing the forest for the trees** — A codebase with 0 events and 20 handlers is a bigger concern than a single long handler

## Quick example

A domain with these elements:

```python
from protean.exceptions import ValidationError


@domain.aggregate
class Order:
    buyer_id = Identifier(required=True)
    total = Float()
    status = String(default="DRAFT")


@domain.aggregate
class Inventory:
    quantity = Integer(default=0)


@domain.command(part_of=Order)
class PlaceOrder:
    buyer_id = Identifier(required=True)
    product_id = Identifier(required=True)
    quantity = Integer(required=True)
    items = List(content_type=Dict())
```

and this handler:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command):
        if len(command.items) == 0:
            raise ValidationError({"items": ["Order must have items"]})
        total = sum(i["price"] * i["qty"] for i in command.items)
        if total > 10000:
            raise ValidationError({"total": ["Order exceeds maximum"]})
        order = Order(buyer_id=command.buyer_id, total=total, status="PLACED")
        current_domain.repository_for(Order).add(order)
        inventory = current_domain.repository_for(Inventory).get(command.product_id)
        inventory.quantity -= command.quantity
        current_domain.repository_for(Inventory).add(inventory)
```

Would produce:

```
CRITICAL: Transaction boundary violation: handler modifies both Order and Inventory (lines 12-14)
HIGH: Logic leak: validation and calculation in handler, not aggregate (lines 5-9)
HIGH: Missing events: Inventory update should be event-driven, not direct (lines 12-14)
MEDIUM: AGGREGATE_WITHOUT_COMMAND_HANDLER on Inventory (from check)
LOW: AGGREGATE_NO_INVARIANTS on Order and Inventory (from check)
```

`AGGREGATE_WITHOUT_COMMAND_HANDLER` is a warning that the table above does not list, so it is reported as MEDIUM. The aggregate skill covers its fix.

## Examples

- [Sample codebase to audit](assets/audit_sample_codebase.py) and [the refactored result](assets/audit_sample_refactored.py)

## Detailed references

- [Detection heuristics](references/detection-heuristics.md) — Detailed patterns for each category
- [Report template](references/report-template.md) — Full report template with examples
- [Anti-patterns catalog](references/anti-patterns.md) — Comprehensive catalog of Protean anti-patterns

## Related skills

- [refactor-extract-value-object](../refactor-extract-value-object/SKILL.md) — Fix primitive obsession
- [refactor-move-logic-to-aggregate](../refactor-move-logic-to-aggregate/SKILL.md) — Fix logic leaks
- [refactor-introduce-events](../refactor-introduce-events/SKILL.md) — Fix transaction boundary violations
- [extract-bounded-context](../extract-bounded-context/SKILL.md): split one domain into two when the cross-aggregate references run both ways
- [coverage-analysis](../coverage-analysis/SKILL.md) — Complementary: find untested code paths

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
