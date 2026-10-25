# Analysis Checklist

The per-step checklist behind the coverage-analysis process: what to record for each element, and how to mark what the tests cover.

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
- Each `self.raise_(EventClass(...))`: record the EventClass and fields passed

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
- Note which aggregate's events it handles (its `part_of`)
- Note the side effect: the command it issues and what changes in the target aggregate
- Note the guard in the target's command handler that makes a repeated command a no-op (events are delivered at least once)

## Step 5: Inventory existing tests

For each test file, map what is covered, using the SKILL.md's "What counts as tested" list for each element. Mark coverage as: **full** (happy + negative), **partial** (happy only), or **none**.

## Step 6: Compare and report gaps

### Severity classification

| Severity | Criteria | Examples |
|----------|----------|----------|
| **HIGH** | Core behavior untested | Aggregate method with no test, invariant never exercised, handler never tested, cross-aggregate side effect unverified |
| **MEDIUM** | Partial coverage | Missing negative test for business rule, event data unverified (only isinstance), entity add/remove untested |
| **LOW** | Nice-to-have | VO custom operation untested, computed property untested, no lifecycle test |

## Step 7: Generate missing tests

Map each gap to a [generate-test-scaffold](../../generate-test-scaffold/SKILL.md) test class with the table in the SKILL.md's Step 4. Two setup points for the generated tests:

- Set `event_processing` and `command_processing` to `"sync"` in the test conftest, so `domain.process()` and event handlers run inside the test (generate-test-scaffold Step 7)
- For cross-aggregate tests, add the target aggregate to the repository before the source event fires

## Related

- [generate-test-scaffold](../../generate-test-scaffold/SKILL.md): Test generation patterns
- [Aggregate test patterns](../../generate-test-scaffold/references/aggregate-tests.md)
- [Handler test patterns](../../generate-test-scaffold/references/handler-tests.md)
- [Integration test patterns](../../generate-test-scaffold/references/integration-tests.md)
