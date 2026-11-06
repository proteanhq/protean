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

For each aggregate, weigh its technical requirements against your team's
practical constraints with the criteria below.

## How do you pick a pattern?

### Score each aggregate against the criteria

Use this rubric to evaluate each aggregate in your domain:

| Criterion | CQRS | Event Sourcing |
| --------- | ---- | -------------- |
| **Audit Requirements** | Basic logging sufficient | Complete audit trail required |
| **Temporal Queries** | Current state queries only | Need "as of time T" queries |
| **State Transitions** | Simple CRUD operations | Complex multi-step workflows |
| **External Integration** | Occasional event publication | Events as primary integration |
| **Team Expertise** | Standard development skills | Event modeling expertise available |
| **Operational Complexity** | Standard database operations | Event store + projection management |

### Count the criteria an aggregate meets

When an aggregate meets **2 or more** of these criteria, choose **Event
Sourcing**:

1. **The aggregate needs a complete audit trail**: Regulatory compliance,
   financial transactions, or business processes requiring complete
   traceability
2. **You need to analyze past states**: Historical reporting, state
   reconstruction, or "what-if" scenario modeling
3. **The aggregate has complex state transitions**: Multi-step workflows with
   intricate business rules and invariants
4. **Other contexts integrate through its events**: Other bounded contexts
   consume domain events as their primary data source
5. **Your teams are ready for it**: Development team understands event modeling
   and operations team can support event stores

In these cases, choose **CQRS**:

- Fewer than 2 Event Sourcing criteria are met
- Aggregate has simple state management needs
- Team or operational constraints favor traditional approaches
- The aggregate needs direct state access to meet its performance requirements

### How do you move an aggregate to the other pattern?

**To move from CQRS to Event Sourcing**:

1. Pause writes temporarily
2. Export current state as synthetic "Imported" event
3. Resume with normal event capturing
4. Update projections to handle synthetic events

**To move from Event Sourcing to CQRS**:

1. Create snapshot from current projection
2. Switch to state-based storage
3. Continue event publication via outbox
4. Archive event stream

## What mistakes should you avoid?

### Avoid these anti-patterns

**Never mix patterns within a single aggregate**: Choose one pattern per
aggregate and apply it consistently throughout that aggregate's lifecycle.

**Review pattern choices as the business changes**: Hold regular architecture
reviews, and check that each aggregate's pattern still fits the current
business needs.
