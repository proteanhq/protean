# Identifying Logic Leaks

How to recognize business logic that doesn't belong where it is.

## The 3-Line Handler Rule

An ideal handler is 3 lines:

```python
@handle(SomeCommand)
def handle_it(self, command):
    aggregate = domain.repository_for(Agg).get(command.id)  # 1. Load
    aggregate.do_something(command.data)                      # 2. Call
    domain.repository_for(Agg).add(aggregate)                 # 3. Persist
```

Every line beyond these three is a candidate for moving into the aggregate.

## Red Flags by Location

### In Handlers

| What you see | What it means | Where it should go |
|-------------|---------------|-------------------|
| `if status == "X": raise` | State guard | Aggregate method (first line) |
| `total = sum(...)` | Calculation | Aggregate method or property |
| `agg.field = value` (multiple) | State mutation | Single aggregate method |
| `raise ValidationError(...)` | Business rule | `@invariant.post` |
| `if len(items) > MAX:` | Constraint check | `@invariant.post` or field constraint |
| `datetime.now()` | Timestamp setting | Aggregate method |

### In API Endpoints

| What you see | Where it should go |
|-------------|-------------------|
| `if request.field > MAX:` | Aggregate invariant (or field constraint) |
| `Order(field1=..., field2=..., status="PLACED")` | Aggregate factory method |
| `repo.get(id)` | Handler (endpoints should only `domain.process()`) |

### In Application Services

| What you see | Where it should go |
|-------------|-------------------|
| Business conditionals | Aggregate method |
| Cross-field validation | Aggregate invariant |
| State transitions | Aggregate method |

## The "Narrate It" Test

Read the handler aloud. If it tells a **story** ("check this, calculate that, set this, verify that"), the logic should move. If it just says **"tell the aggregate to do it"**, it's correct.

```python
# Tells a story (BAD):
"Get the ticket, check if it's closed, check if it's open,
 set the status to closed, set the resolution, set the closed_at time, save it"

# Delegates (GOOD):
"Get the ticket, close it with this resolution, save it"
```

## Related

- [anti-patterns.md](anti-patterns.md) — Common refactoring mistakes
