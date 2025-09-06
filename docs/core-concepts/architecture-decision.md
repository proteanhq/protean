# Choosing Between Patterns

Protean supports both CQRS and Event Sourcing architectural patterns.

From a purist architectural standpoint, having a single, consistent pattern
across a domain makes perfect sense - it maintains conceptual integrity and
reduces cognitive load. But in practice, different aggregates within the
same domain often have vastly different characteristics and requirements.

While it is preferable to have a single pattern for the entire domain,
forcing inappropriate patterns onto aggregates creates its own cognitive
burden. So choosing the right pattern for each aggregate is one of the
most important decisions you'll make for your domain model.

This guide provides a systematic approach to making these architectural
decisions, balancing technical requirements with practical constraints.

## Decision Framework

### Pattern Selection Criteria

Use this rubric to evaluate each aggregate in your domain:

| Criterion | CQRS | Event Sourcing |
| --------- | ---- | -------------- |
| **Audit Requirements** | Basic logging sufficient | Complete audit trail required |
| **Temporal Queries** | Current state queries only | Need "as of time T" queries |
| **State Transitions** | Simple CRUD operations | Complex multi-step workflows |
| **External Integration** | Occasional event publication | Events as primary integration |
| **Team Expertise** | Standard development skills | Event modeling expertise available |
| **Operational Complexity** | Standard database operations | Event store + projection management |

### Decision Matrix

Choose **Event Sourcing** when an aggregate meets **2 or more** of these criteria:

1. **Strong auditability required**: Regulatory compliance, financial transactions,
   or business processes requiring complete traceability
2. **Temporal analysis needed**: Historical reporting, state reconstruction,
   or "what-if" scenario modeling
3. **Complex state transitions**: Multi-step workflows with intricate business
   rules and invariants
4. **Event-driven integration**: Other bounded contexts consume domain events
   as their primary data source
5. **Team readiness**: Development team understands event modeling and
   operations team can support event stores

Choose **CQRS** when:

- Fewer than 2 Event Sourcing criteria are met
- Aggregate has simple state management needs
- Team or operational constraints favor traditional approaches
- Performance requirements favor direct state access

### Migration Strategies

**From CQRS to Event Sourcing**:

1. Pause writes temporarily
2. Export current state as synthetic "Imported" event
3. Resume with normal event capturing
4. Update projections to handle synthetic events

**From Event Sourcing to CQRS**:

1. Create snapshot from current projection
2. Switch to state-based storage
3. Continue event publication via outbox
4. Archive event stream

## Common Pitfalls

### Anti-Patterns to Avoid

**Never mix patterns within a single aggregate**: Choose one pattern per
aggregate and apply it consistently throughout that aggregate's lifecycle.

**Avoid architectural drift**: Regular architecture reviews ensure pattern
choices remain aligned with evolving business needs.
