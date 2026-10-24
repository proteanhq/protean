# Single-Aggregate Read Model

A single-aggregate read model is a query-optimized view of one aggregate's data. It is the simplest and most common read model.

## When to use

- The UI needs a flat, queryable view of aggregate data
- You want to avoid loading the full aggregate for read-only queries
- The projection fields are a subset or transformation of one aggregate's data

## Step-by-step

SKILL.md Steps 1 to 6 hold the full Product → ProductListing code. The choices behind each step:

1. **Identify the query need**: Ask "What does the consumer (UI, API, report) need to display?" Map those needs to flat fields.
2. **Define events**: Each state change that should update the read model needs an event. Events are named in past tense (`ProductAdded`, `PriceChanged`) and carry the data needed for the projection.
3. **Define the projection**: Flatten the data into basic field types. The identifier field should match the aggregate's identity.
4. **Raise events from the aggregate**: Add factory methods or domain methods that raise the events.
5. **Build the projector**: The projector maps events to projection operations (create, update, delete).
6. **Read the model back**: A query handler reads through `domain.view_for`, which is read-only.

## Key patterns

- **One projector per projection**: Each projection has its own dedicated projector, and that projector handles every event that changes the projection
- **Event-per-change**: Each distinct state change gets its own event type

## Complete example

See [read_model_single_aggregate.py](../assets/read_model_single_aggregate.py) for a complete runnable example with create, price update, and stock update events.
