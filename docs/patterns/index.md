# Patterns & Recipes

This section contains in-depth guides for recurring patterns in domain-driven
applications built with Protean. Each pattern goes beyond the basics covered
in the main guides, providing architectural context, trade-off analysis, and
concrete implementation strategies.

## Available Patterns

- **[Command Idempotency](command-idempotency.md)** -- Ensuring that processing
  the same command multiple times produces the same effect as processing it
  once. Covers Protean's three-layer idempotency model, idempotency keys,
  and handler-level strategies for different operation types.
