# When to Use Domain Services

## Decision guide

```
Does the logic belong to a single aggregate?
├── Yes → Use an aggregate method
│
└── No → Does it span multiple aggregates?
    ├── Yes → Is it synchronous business logic?
    │   ├── Yes → Domain service
    │   └── No → Event handler (async, eventual consistency)
    │
    └── Is it orchestration (load/persist)?
        └── Yes → Command handler
```

## Domain service vs other patterns

| Scenario | Use | Why |
|----------|-----|-----|
| Transfer funds between accounts | Domain service | Cross-aggregate logic, synchronous |
| Reduce inventory on order ship | Event handler | Async, eventual consistency |
| Load order, call method, persist | Command handler | Orchestration, not business logic |
| Calculate order total | Aggregate method | Single aggregate logic |
| Check balance before debit | Domain service pre-invariant | Cross-aggregate validation |
| Authorize a request | Handler guard (Layer 4) | Context-dependent check |

## Rules for domain services

1. **Stateless**: no instance state beyond the aggregates passed in
2. **No persistence**: the caller (a handler) persists
3. **No side effects**: change only the primary aggregate passed in; the others change through an event and a command
4. **Cross-aggregate**: involves 2+ aggregates
5. **Business logic**: leave orchestration to handlers and authorization to handler guards
