Build a small Protean project that models ordering and payment as two separate
bounded contexts.

Requirements:

- An order context with an `Order` aggregate, holding at least an order status,
  with a command and a command handler that create an `Order` and persist it.
- A payment context with a `Payment` aggregate, holding at least an amount, with
  a command and a command handler that create a `Payment` and persist it.
- Keep the two contexts in separate modules: the order slice under the order
  context, the payment slice under the payment context.
- The project must pass `protean verify` with no findings.

Write the project's files, then run verify to confirm it is green.
