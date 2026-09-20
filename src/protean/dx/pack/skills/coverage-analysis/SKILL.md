---
name: coverage-analysis
description: Analyze Protean domain code to identify untested code paths and generate missing tests. Catalogs all testable elements (aggregate methods, invariants, events, handlers, value object operations, entity management) from domain definitions, compares against existing tests, produces a gap report with severity classification, and generates missing tests using generate-test-scaffold patterns. Use when the user asks to "find untested code", "analyze test coverage", "check what's missing tests", "identify test gaps", "improve test coverage", "what code paths are untested", "audit my tests", "find missing tests", "review test completeness", or when they want to ensure comprehensive domain test coverage for their Protean application.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [generate-test-scaffold]
---

# Coverage Analysis

Analyze Protean domain code to identify untested business logic and generate missing tests in a single pass.

## What this produces

| Output | Purpose |
|--------|---------|
| **Testable element catalog** | Every aggregate method, invariant, event, handler, VO operation |
| **Existing test inventory** | What current tests already cover |
| **Gap report** | Untested code paths classified by severity |
| **Generated tests** | Missing tests following generate-test-scaffold patterns |

## Testable element categories

| Category | What to catalog | How to detect |
|----------|----------------|---------------|
| Aggregate factory methods | `@classmethod` that returns `cls(...)` | Look for classmethods on aggregates |
| State-change methods | Instance methods that mutate `self.field` | Assignments to `self.status`, `self.field`, etc. |
| Events raised | `self.raise_(EventClass(...))` calls | Grep for `raise_` in aggregate methods |
| User-defined invariants | `@invariant.pre` / `@invariant.post` | Decorator usage on aggregate methods |
| Business rules | Guard conditions that raise errors | `if ... raise ValueError/ValidationError` |
| Command handlers | `@handle(CommandClass)` methods | Handler methods in `@domain.command_handler` |
| Event handlers | `@handle(EventClass)` methods | Handler methods in `@domain.event_handler` |
| Value object operations | Custom methods on VOs | Non-dunder instance methods on `@domain.value_object` |
| Entity management | `add_<entities>()` / `remove_<entities>()` | Aggregate methods managing child entities |

## Information to gather

Before analyzing, identify:

- [ ] All domain Python files (aggregate definitions, commands, events, handlers)
- [ ] All existing test files for those domain elements
- [ ] The domain instance (`domain = Domain(...)`)
- [ ] Which aggregate each element belongs to

## Process

### Step 1: Catalog testable elements

Read all domain files and build a structured inventory per aggregate:

```python
# For each aggregate, catalog:
{
    "Ticket": {
        "factory_methods": ["create"],
        "state_change_methods": ["assign", "close", "escalate_priority"],
        "events_raised": {
            "create": ["TicketCreated"],
            "assign": ["TicketAssigned"],
            "close": ["TicketClosed"],
        },
        "invariants": ["assigned_ticket_must_have_assignee"],
        "business_rules": {
            "assign": ["status must not be closed"],
            "close": ["status must not be open"],
        },
    },
    "Priority": {
        "vo_operations": ["escalate"],
        "business_rules": {"escalate": ["cannot escalate beyond critical"]},
    },
}
```

**Detection patterns:**
- **Factory methods**: `@classmethod` that calls `cls(...)` and optionally `raise_()`
- **State-change methods**: Instance methods that assign `self.status = ...` or `self.field = ...`
- **Events raised**: Lines containing `self.raise_(SomeEvent(...))`
- **Invariants**: Methods decorated with `@invariant.pre` or `@invariant.post`
- **Business rules**: `if` conditions followed by `raise ValueError` or `raise ValidationError`
- **VO operations**: Non-dunder instance methods on `@domain.value_object` classes
- **Entity management**: Methods calling `self.add_<collection>()` or `self.remove_<collection>()`

### Step 2: Inventory existing tests

Read all test files and map what is already tested:

```python
{
    "Ticket": {
        "factory_methods_tested": ["create"],       # covered
        "state_changes_tested": ["assign"],          # close NOT tested
        "events_verified": ["TicketCreated"],        # TicketClosed NOT verified
        "invariants_tested": [],                     # NONE tested
        "business_rules_tested": {},                 # NONE tested
    }
}
```

**What counts as "tested":**
1. **Factory method**: Test calls the method and asserts resulting state
2. **State-change method**: Test calls the method and asserts the state transition
3. **Event raised**: Test asserts `isinstance(aggregate._events[N], EventClass)` AND checks event field values
4. **Invariant**: Test triggers the invariant condition and uses `pytest.raises`
5. **Business rule**: Test for the happy path AND test for the rejection case
6. **Command handler**: Test calls `domain.process(Command(...), asynchronous=False)` and verifies persisted state
7. **Event handler**: Test verifies the target aggregate state changed after the source aggregate was persisted
8. **VO operation**: Test calls the custom method and asserts the result

### Step 3: Identify gaps

Compare catalog against inventory. Classify each gap:

| Severity | Criteria |
|----------|----------|
| **HIGH** | Core behavior untested: aggregate methods, invariants, handler orchestration, cross-aggregate side effects |
| **MEDIUM** | Partial coverage: missing negative tests, event data unverified, entity operations untested |
| **LOW** | Nice-to-have: VO operations, computed properties, lifecycle tests |

### Step 4: Generate missing tests

For each gap, generate tests following [generate-test-scaffold](../generate-test-scaffold/SKILL.md) patterns:

| Gap type | Test class pattern | Scaffold reference |
|----------|-------------------|-------------------|
| Aggregate method | `Test{Aggregate}Behavior` | generate-test-scaffold Step 2 |
| Invariant / business rule | `Test{Aggregate}BusinessRules` | generate-test-scaffold Step 3 |
| Command handler | `TestHandlerProcessing` | generate-test-scaffold Step 4 |
| Event handler side effect | `TestCrossAggregateFlow` | generate-test-scaffold Step 5 |
| End-to-end lifecycle | `TestLifecycle` | generate-test-scaffold Step 6 |

Use `_events.clear()` to isolate event assertions when testing a method after a factory that also raises events.

### Step 5: Present gap report with generated tests

```markdown
## Coverage Analysis Report

### Domain Elements Cataloged
- Aggregates: [list with method counts]
- Commands: [list]
- Events: [list]
- Handlers: [list]

### Coverage Summary
- Tested: X/Y testable elements (Z%)
- Gaps found: N (H high, M medium, L low)

### Gaps (by severity)

#### HIGH
1. [description] — generated test class: `TestXxx`

#### MEDIUM
1. [description] — generated test class: `TestXxx`

#### LOW
1. [description] — generated test class: `TestXxx`

### Generated Tests
[Complete test code for all gaps]
```

## What NOT to flag as gaps

Do not report missing tests for framework-guaranteed behavior:
- VO construction, equality, immutability — guaranteed by `@domain.value_object`
- Command/event immutability — guaranteed by decorators
- Field-level validation (`required`, `max_length`, `min_value`, `choices`) — Protean Layer 1
- Element registration in `domain.registry` — guaranteed if decorator is used
- `meta_.part_of` associations, `meta_.stream_category` — framework wiring
- Command `.payload` dict access — framework feature

## Common mistakes

1. **Flagging framework guarantees as gaps** — Don't report missing tests for VO immutability, field validation, or registry presence
2. **Missing negative tests** — Every business rule (`if ... raise`) needs both a happy path test AND a rejection test
3. **Checking only isinstance for events** — Event data verification (field values) is a separate coverage point from event type checking
4. **Forgetting cross-aggregate handlers** — Event handlers that listen to OTHER aggregates' streams are often the most undertested
5. **Not tracing raise_() to event classes** — Each `raise_()` call means there should be a test verifying that specific event

## Complete examples

- [Issue tracker domain](assets/coverage_domain_with_gaps.py) — Domain with all testable element categories

## Detailed references

- [Analysis checklist](references/analysis-checklist.md) — Step-by-step checklist for thorough analysis

## Related skills

- [generate-test-scaffold](../generate-test-scaffold/SKILL.md) — Test generation patterns (used in Step 4)
- [aggregate](../aggregate/SKILL.md) — Aggregate definition patterns
- [command-handler](../command-handler/SKILL.md) — Command handler patterns
- [event-handler](../event-handler/SKILL.md) — Event handler patterns
- [value-object](../value-object/SKILL.md) — Value object patterns
