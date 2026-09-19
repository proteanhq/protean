Build a small Protean project that models orders and the customers who place
them, as two separate aggregates.

Requirements:

- An `Order` aggregate that holds at least an order status, with a command and a
  command handler that create an `Order` and persist it.
- A `Customer` aggregate that holds at least the customer's name, with a command
  and a command handler that create a `Customer` and persist it.
- Each command, event, and handler must belong to the aggregate it acts on: the
  order slice under `Order`, the customer slice under `Customer`.
- The project must pass `protean verify` with no findings.

Write the project's files, then run verify to confirm it is green.
