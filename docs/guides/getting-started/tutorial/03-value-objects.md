# Chapter 3: Value Objects — Describing Things

So far our `Book` aggregate uses primitive fields — `Float` for price,
`String` for everything else. But a price is not just a number. It has a
currency. An address is not just a string. It has a street, city, and zip
code. In this chapter, we introduce **value objects** — a way to model
these rich, descriptive concepts.

## What Are Value Objects?

A value object is an immutable object defined by its attributes rather
than an identity. Two value objects with the same attributes are
considered equal — just like two $10 bills are interchangeable regardless
of their serial numbers.

Key characteristics:

- **Immutable** — once created, they cannot be changed
- **No identity** — compared by value, not by ID
- **Self-validating** — they can enforce their own rules

## The Money Value Object

Let's replace Book's plain `Float` price with something more meaningful:

```python
{! docs_src/guides/getting-started/tutorial/ch03.py [ln:1-13] !}
```

`Money` captures both the amount and the currency. This prevents subtle
bugs — you would never accidentally add dollars to euros.

### Embedding in an Aggregate

Use the `ValueObject` field to embed a value object inside an aggregate:

```python
{! docs_src/guides/getting-started/tutorial/ch03.py [ln:30-36] !}
```

Now creating a book looks like this:

```python
book = Book(
    title="The Great Gatsby",
    author="F. Scott Fitzgerald",
    price=Money(amount=12.99),
)
print(f"${book.price.amount} {book.price.currency}")
# $12.99 USD
```

The `currency` defaults to `"USD"` so we only need to specify the amount.
When we need a different currency, we pass it explicitly:
`Money(amount=29.99, currency="EUR")`.

!!! question "Why Not Just a Float?"
    A `Float` field stores only the number. With `Money`, you also capture
    the currency — and can later add behavior like formatting or conversion.
    Value objects make your domain model *self-documenting*: anyone reading
    the code immediately understands that price is a monetary amount, not
    just an arbitrary number.

## The Address Value Object

We will need shipping addresses when we build orders later. Let's define
`Address` now:

```python
{! docs_src/guides/getting-started/tutorial/ch03.py [ln:17-24] !}
```

The `country` field defaults to `"US"`. We will use this value object in
a later chapter when we add orders and shipping.

## Equality by Value

Value objects are compared by their attributes, not by some hidden
identity:

```python
price1 = Money(amount=12.99, currency="USD")
price2 = Money(amount=12.99, currency="USD")
price3 = Money(amount=14.99, currency="USD")

price1 == price2  # True  — same values
price1 == price3  # False — different amount
```

This is different from aggregates and entities, which are compared by
their identity (ID). Two `Book` objects with the same title are still
different books if they have different IDs.

## Immutability in Practice

Value objects are frozen after creation. Attempting to modify one raises
an error:

```python
>>> price = Money(amount=12.99)
>>> price.amount = 14.99
InvalidOperationError: Money objects are immutable ...
```

To "change" a value, you replace the entire object:

```python
book.price = Money(amount=14.99, currency="USD")
```

This guarantees that value objects are always in a consistent state —
there is no way to corrupt them through partial updates.

## Deciding: Field vs Value Object

When should you use a plain field and when should you extract a value
object? Here is a simple heuristic:

| Use a Field When... | Use a Value Object When... |
|---------------------|---------------------------|
| The value is truly a single thing (a name, a count) | The value has multiple related attributes (amount + currency) |
| No special rules apply | The value has its own validation rules |
| It has no domain meaning beyond the data | It represents a domain concept worth naming |

If you find yourself adding the same group of fields to multiple
aggregates (like `street`, `city`, `zip_code`), that is a strong
signal to extract a value object.

## Full Source

```python
{! docs_src/guides/getting-started/tutorial/ch03.py !}
```

Run it:

```shell
$ python bookshelf.py
Book: The Great Gatsby
Price: 12.99 USD

Money(12.99, USD) == Money(12.99, USD)? True
Money(12.99, USD) == Money(14.99, USD)? False

Retrieved: The Great Gatsby, $12.99

Address: 123 Main St, Springfield, IL

All checks passed!
```

## Summary

In this chapter you learned:

- **Value objects** are immutable, identity-less objects compared by value.
- The **`ValueObject` field** embeds a value object inside an aggregate.
- Use value objects to model concepts with multiple attributes (`Money`,
  `Address`) rather than primitive fields.
- Value objects cannot be modified after creation — replace them instead.

Our bookstore has books with proper prices. In the next chapter we will
introduce **entities** and **associations** — child objects with identity
that live inside an aggregate. We will build the `Order` aggregate with
its `OrderItem` entities.

## Next

[Chapter 4: Entities and Associations →](04-entities-and-associations.md)
