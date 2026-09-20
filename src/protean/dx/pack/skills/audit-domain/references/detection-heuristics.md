# Detection Heuristics

Detailed patterns for identifying each anti-pattern category during a domain audit.

## 1. Logic Leak Detection

**What to grep for in handler files:**

```python
# Calculations in handlers
total = ...
price = ... * ...
discount = ...

# Conditionals beyond simple null/existence checks
if len(items) > ...
if status == ...
if amount > ...

# State transitions in handlers
order.status = "PLACED"  # Should be inside aggregate method

# Direct attribute assignment from handler
aggregate.field = command.value  # Multiple of these = logic leak
```

**Threshold**: A handler method with more than ~5 statements beyond `repo.get()`, `aggregate.method()`, `repo.add()` is suspect.

**False positives to ignore**:
- Simple mapping: `order = Order(customer_id=command.customer_id)` is fine
- Single conditional for command routing: `if command.type == "express":` can be OK
- Logging statements

## 2. Primitive Obsession Detection

**Field group patterns to look for:**

| Pattern | Should be | VO name |
|---------|-----------|---------|
| `amount` + `currency` | `ValueObject(Money)` | Money |
| `street` + `city` + `state` + `zip_code` | `ValueObject(Address)` | Address |
| `latitude` + `longitude` | `ValueObject(Coordinates)` | Coordinates |
| `first_name` + `last_name` | `ValueObject(PersonName)` | PersonName |
| `start_date` + `end_date` | `ValueObject(DateRange)` | DateRange |
| `quantity` + `unit` | `ValueObject(Measurement)` | Measurement |

**Single-field patterns:**

| Pattern | Should be |
|---------|-----------|
| `email = String(...)` with email validator | `ValueObject(Email)` |
| `phone = String(...)` with phone validator | `ValueObject(PhoneNumber)` |
| `price = Float(...)` without currency | `ValueObject(Money)` |
| `url = String(...)` with URL validator | `ValueObject(Url)` |

**Cross-aggregate repetition**: If the same field group appears in 2+ aggregates, it's almost certainly a VO candidate.

## 3. Transaction Boundary Violation Detection

**What to grep for:**

```python
# Multiple repository accesses
domain.repository_for(AggregateA)
domain.repository_for(AggregateB)  # Second aggregate = violation

# Multiple self.repository usages on different types
self.repository.add(order)
other_repo.add(inventory)  # Different aggregate type
```

**How to confirm**: Check if both repositories are used within the same `@handle` method. A handler file that imports two repository types but uses them in different methods is fine.

## 4. God Aggregate Detection

**Quantitative signals:**

| Metric | Warning threshold | Critical threshold |
|--------|------------------|--------------------|
| Field count | 12 | 20 |
| Public method count | 8 | 15 |
| Invariant count | 5 | 10 |
| HasMany associations | 3 | 5 |
| Lines of code | 100 | 200 |

**Qualitative signals:**
- Fields that could be grouped into unrelated "zones" (order info vs. shipping info vs. billing info)
- Methods that only touch a subset of fields (shipping methods don't touch payment fields)
- Entity types under the same aggregate that don't interact with each other

## 5-11. Remaining Categories

**Manual UoW (5)**: Grep for `UnitOfWork` in handler files. Any match is a finding.

**Direct handler calls (6)**: Grep for `Handler()` instantiation or handler method calls outside of `domain.process()`.

**Scattered validation (7)**: Grep for `ValidationError` or `ValueError` in handler and endpoint files. Check if the same validation exists as an `@invariant`.

**Circular import risk (8)**: Grep for `part_of=` (without quotes around the value) in command, event, entity, and value object files.

**Mock overuse (9)**: Grep for `Mock`, `MagicMock`, `@patch` in test files. Count the ratio of mocked vs. real domain tests.

**Missing versioning (10)**: Find all `@domain.event` classes and check for `__version__` attribute.

**Missing events (11)**: In handlers, look for loading a second aggregate type and mutating it. In aggregate methods, look for calls to external repositories.

## Severity Calibration

When the same code triggers multiple categories, report all of them but group them in the recommendation. For example, a handler that validates, calculates, and modifies two aggregates should be reported as three findings but recommended as one refactoring unit.
