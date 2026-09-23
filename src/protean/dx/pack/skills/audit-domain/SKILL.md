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

## Detection categories

Scan for these anti-patterns in order. Each has a detection heuristic and a linked fix.

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
- Multiple `self.repository.add()` calls on different aggregate types
- Multiple `domain.repository_for(X)` calls in one handler
- Loading and mutating a second aggregate inside a handler

**Severity**: CRITICAL
**Fix**: [refactor-introduce-events](../refactor-introduce-events/SKILL.md)

### 4. God aggregate — oversized aggregate root

**Detect**: Aggregates with too many fields, methods, or responsibilities.

**Signals**:
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
**Fix**: refactor-add-invariants (planned)

### 8. Circular import risk — class references in DTOs

**Detect**: Commands, events, entities, or value objects using class references for `part_of`
instead of string references.

**Signals**:
- `@domain.command(part_of=OrderAggregate)` (class, not string)
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

### Step 1: Discover domain files

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

### Step 2: Scan each file

For every domain file, check all 11 detection categories. Record each finding with:
- **File and line number**
- **Category** (1-11 from above)
- **Severity** (CRITICAL / HIGH / MEDIUM / LOW)
- **Description** — what was found
- **Suggestion** — one-sentence fix

### Step 3: Produce the report

```markdown
## Domain Audit Report

### Summary
- Files scanned: N
- Aggregates found: N
- Handlers found: N
- Issues found: N (C critical, H high, M medium, L low)

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

### Step 4: Suggest refactoring order

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

Scanning a file like this:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command):
        if len(command.items) == 0:
            raise ValidationError("Order must have items")
        total = sum(i.price * i.qty for i in command.items)
        if total > 10000:
            raise ValidationError("Order exceeds maximum")
        order = Order(buyer_id=command.buyer_id, total=total, status="PLACED")
        self.repository.add(order)
        inventory = domain.repository_for(Inventory).get(command.product_id)
        inventory.quantity -= command.quantity
        domain.repository_for(Inventory).add(inventory)
```

Would produce:

```
CRITICAL: Transaction boundary violation — handler modifies both Order and Inventory (line 10-12)
HIGH: Logic leak — validation and calculation in handler, not aggregate (lines 3-8)
HIGH: Missing events — Inventory update should be event-driven, not direct (line 10-12)
```

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
