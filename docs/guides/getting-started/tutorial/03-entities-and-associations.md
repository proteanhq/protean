# Chapter 3: Entities and Associations

In this chapter we will build the `Order` aggregate with child entities
and associations, giving our bookstore the ability to take orders.

## The Order Aggregate

A bookstore doesn't just sell books — it takes orders. An order contains
multiple items, has a shipping address, and tracks its status. Let's model
it:

```python
{! docs_src/guides/getting-started/tutorial/ch03.py [ln:1-12] !}
```

```python
{! docs_src/guides/getting-started/tutorial/ch03.py [ln:40-56] !}
```

Notice that:

- `shipping_address` uses the `Address` value object we created in the
  previous chapter.
- `status` uses a Python `Enum` with a default of `PENDING`.
- `items` is a `HasMany` association — it holds a collection of
  `OrderItem` entities.

## Child Entities

Each order item is an **entity** — an object with its own identity that
belongs to the Order aggregate. Unlike value objects, entities can be
individually tracked:

```python
{! docs_src/guides/getting-started/tutorial/ch03.py [ln:63-69] !}
```

The `part_of=Order` parameter tells Protean this entity belongs to the
Order aggregate. It cannot exist independently — it is always accessed
through its parent.

## Creating an Order

Let's create an order with items and a shipping address:

```python
{! docs_src/guides/getting-started/tutorial/ch03.py [ln:78-111] !}
```

Run it:

```shell
$ python bookshelf.py
Order for: Alice Johnson
Status: PENDING
Ship to: Portland, OR
Items (2):
  - The Great Gatsby x1 @ $12.99
    Item ID: a1b2c3d4-...
  - Brave New World x2 @ $14.99
    Item ID: e5f6g7h8-...
```

Notice that each `OrderItem` has its own unique ID — that is what makes
it an entity rather than a value object. The entire cluster (Order +
OrderItems + Address) is persisted as a single unit.

## Adding Items After Creation

We can also add items to an existing order:

```python
{! docs_src/guides/getting-started/tutorial/ch03.py [ln:122-139] !}
```

The output should show:

```
Retrieved order: Alice Johnson
Items: 2
After adding item: 3 items
All checks passed!
```

## What We Built

- An **Order aggregate** with status tracking and a shipping address.
- **OrderItem entities** — child objects with their own identity, linked
  to the parent Order via `HasMany`.
- An **aggregate cluster**: Order + OrderItems + Address persisted as
  one unit.

Our domain now has two aggregates: `Book` and `Order`. In the next
chapter, we will add business rules that keep these aggregates in a
valid state.

## Full Source

```python
{! docs_src/guides/getting-started/tutorial/ch03.py !}
```

## Next

[Chapter 4: Business Rules →](04-business-rules.md)
