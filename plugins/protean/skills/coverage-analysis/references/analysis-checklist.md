# Analysis Checklist

Step-by-step process for analyzing Protean domain code coverage.

## Overview

This checklist walks through a systematic coverage analysis of Protean domain code. Follow each step to ensure no testable element is missed.

## Code

Complete example domain in [assets/coverage_domain_with_gaps.py](../assets/coverage_domain_with_gaps.py).

## Step 1: Identify all domain files

- Locate files containing `domain = Domain(...)` or importing from a domain module
- List all classes decorated with `@domain.aggregate`, `@domain.entity`, `@domain.value_object`, `@domain.event`, `@domain.command`, `@domain.command_handler`, `@domain.event_handler`

## Step 2: Catalog each aggregate

For each `@domain.aggregate` class, record:

### Factory methods
- `@classmethod` methods that call `cls(...)`
- Note if they call `raise_()` (event should be tested)

### State-change methods
- Instance methods that assign to `self.field = value`
- Note status transitions (before/after values)

### Events raised
- Each `self.raise_(EventClass(...))` — record the EventClass and fields passed

### Invariants
- Methods decorated with `@invariant.pre` or `@invariant.post`
- Note the condition being guarded and the exception raised

### Business rules
- `if ... raise ValueError` or `raise ValidationError` patterns
- Note the condition and the rejection message

### Entity management
- Methods calling `self.add_<collection>()` or `self.remove_<collection>()`

### Computed properties
- `@property` methods that compute derived values

## Step 3: Catalog value objects

For each `@domain.value_object` class:
- List all non-dunder, non-property instance methods (user operations)
- Note any `raise ValueError` patterns (business rules)

## Step 4: Catalog handlers

### Command handlers
- For each `@domain.command_handler`, list `@handle(CommandClass)` methods
- Note what the handler does: creates aggregate? loads and mutates? validates?

### Event handlers
- For each `@domain.event_handler`, list `@handle(EventClass)` methods
- Note `stream_category` (which aggregate's events it listens to)
- Note the side effect (what changes in the target aggregate)

## Step 5: Inventory existing tests

For each test file, map what is covered:
- Which aggregate methods are called in tests?
- Which events are verified with `isinstance` AND field value checks?
- Which invariants are triggered with `pytest.raises`?
- Which business rules are tested for both happy and rejection paths?
- Which handlers are tested with `domain.process()`?
- Which cross-aggregate side effects are verified?

Mark coverage as: **full** (happy + negative), **partial** (happy only), or **none**.

## Step 6: Compare and report gaps

Cross-reference the catalog against the test inventory.

### Severity classification

| Severity | Criteria | Examples |
|----------|----------|----------|
| **HIGH** | Core behavior untested | Aggregate method with no test, invariant never exercised, handler never tested, cross-aggregate side effect unverified |
| **MEDIUM** | Partial coverage | Missing negative test for business rule, event data unverified (only isinstance), entity add/remove untested |
| **LOW** | Nice-to-have | VO custom operation untested, computed property untested, no lifecycle test |

## Step 7: Generate missing tests

For each gap, use [generate-test-scaffold](../../generate-test-scaffold/SKILL.md) patterns:

| Gap type | Test class pattern | Scaffold step |
|----------|-------------------|---------------|
| Aggregate factory/method | `Test{Aggregate}Behavior` | Step 2 |
| Invariant / business rule | `Test{Aggregate}BusinessRules` | Step 3 |
| Command handler | `TestHandlerProcessing` | Step 4 |
| Event handler side effect | `TestCrossAggregateFlow` | Step 5 |
| End-to-end lifecycle | `TestLifecycle` | Step 6 |

**Key patterns:**
- Use `_events.clear()` to isolate event assertions after a factory that also raises events
- Always pass `asynchronous=False` to `domain.process()` in tests
- For cross-aggregate tests, ensure the target aggregate exists in the repository before the source event fires

## Common analysis mistakes

1. **Flagging framework guarantees** — VO immutability, field validation, registration are NOT gaps
2. **Missing negative tests** — Every `if ... raise` needs both happy path and rejection test
3. **isinstance-only event checks** — Verifying event type without checking field values is partial coverage
4. **Forgetting cross-aggregate handlers** — Event handlers listening to other streams are often undertested
5. **Not tracing raise_() calls** — Each `raise_()` should have a corresponding test

## Related

- [generate-test-scaffold](../../generate-test-scaffold/SKILL.md) — Test generation patterns
- [Aggregate test patterns](../../generate-test-scaffold/references/aggregate-tests.md)
- [Handler test patterns](../../generate-test-scaffold/references/handler-tests.md)
- [Integration test patterns](../../generate-test-scaffold/references/integration-tests.md)
