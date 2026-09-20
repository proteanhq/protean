---
description: Core Protean framework conventions — always active when writing Protean application code
globs: "**/*.py"
---

# Protean Conventions

## Naming

- **Commands** use imperative verbs: `PlaceOrder`, `CancelSubscription`, `AddLineItem`
- **Events** use past tense: `OrderPlaced`, `SubscriptionCancelled`, `LineItemAdded`
- **Aggregates, Entities, Value Objects** use domain nouns: `Order`, `LineItem`, `Money`
- **Handlers** are named after what they handle: `PlaceOrderHandler`, `OrderPlacedHandler`

## References

- Always use **string references** for `part_of` to avoid circular imports:
  ```python
  # Good
  @domain.event(part_of="Order")

  # Bad — causes circular import issues
  @domain.event(part_of=Order)
  ```

## Fields

- Use **annotation-style** field definitions — both patterns are supported:
  ```python
  # Preferred: type annotation with field instance
  title: String = String(required=True, max_length=200)

  # Also valid: field instance as annotation
  title: String(required=True, max_length=200)
  ```
- Never manually define auto-generated association helpers (`add_*`, `remove_*` for HasMany)

## Invariants

- One business rule per `@invariant` decorator — keep them granular
- Use `@invariant.post` for most invariants (checked after state changes)
- Use `@invariant.pre` sparingly (checked before state changes, not during init)
- Document the business rule in the invariant method's docstring

## Aggregates

- Aggregates are **transaction boundaries** — one aggregate per transaction
- All state mutations go through aggregate methods, never directly on entities
- Keep aggregates small — large aggregates signal a modeling problem

## Domain Context

- Always wrap domain operations in `domain.domain_context()`
- Use `domain.init(traverse=False)` in tests when registering elements manually
