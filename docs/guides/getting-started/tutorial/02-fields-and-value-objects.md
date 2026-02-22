# Chapter 2: Rich Fields and Value Objects

In this chapter we will enrich our `Book` aggregate with more field types
and replace the plain `Float` price with a `Money` value object that
captures both amount and currency.

## Enriching the Book Aggregate

Our Book currently has just `title`, `author`, `isbn`, and `price`. A real
bookstore needs more. Let's add several new fields:

```python
{! docs_src/guides/getting-started/tutorial/ch02.py [ln:1-8] !}
```

```python
{! docs_src/guides/getting-started/tutorial/ch02.py [ln:11-20] !}
```

```python
{! docs_src/guides/getting-started/tutorial/ch02.py [ln:52-63] !}
```

We have added:

- **`Text`** for `description` — long-form text, unlike `String` which has a
  `max_length` cap.
- **`Date`** for `publication_date` — a date without time.
- **`Integer`** for `page_count` — whole numbers.
- **`Boolean`** for `in_print` — true/false with a default of `True`.
- **`List`** for `tags` — a list of strings.
- **`choices=Genre`** on the `genre` field restricts values to a Python `Enum`.

For the complete list of field types and options, see the
[Fields reference](../../../reference/fields/index.md).

### Constraining with Choices

The `genre` field uses a Python `Enum` to restrict valid values.
Attempting to create a book with an invalid genre raises a `ValidationError`:

```python
>>> Book(title="Test", author="Test", genre="ROMANCE")
ValidationError: {'genre': ["Value 'ROMANCE' is not a valid choice. ..."]}
```

Notice that Protean catches invalid values at the domain boundary — invalid
aggregates never enter your domain.

## From Float to Money

A `Float` stores only a number, but a price also has a currency. Let's
create a `Money` value object to capture both. A value object is an
immutable object defined by its attributes, with no identity of its own
(see [Value Objects](../../../concepts/building-blocks/value-objects.md)
for more).

```python
{! docs_src/guides/getting-started/tutorial/ch02.py [ln:24-32] !}
```

Now embed it in the `Book` aggregate using a `ValueObject` field:

```python
{! docs_src/guides/getting-started/tutorial/ch02.py [ln:52-63] !}
```

Notice that `price` is now declared with `ValueObject(Money)` instead of
`Float()`. When we create a book, we pass a `Money` instance:

```python
book = Book(
    title="The Great Gatsby",
    author="F. Scott Fitzgerald",
    price=Money(amount=12.99),
)
print(f"Price: ${book.price.amount} {book.price.currency}")
# Price: $12.99 USD
```

The currency defaults to `"USD"` because we set `default="USD"` on the
field. The price now carries both pieces of information together.

## Value Equality

Two value objects with the same attributes are considered equal — identity
does not matter, only the values:

```python
price1 = Money(amount=12.99, currency="USD")
price2 = Money(amount=12.99, currency="USD")
price3 = Money(amount=14.99, currency="USD")

print(price1 == price2)  # True — same values
print(price1 == price3)  # False — different amount
```

## The Address Value Object

Let's also create an `Address` value object for shipping addresses:

```python
{! docs_src/guides/getting-started/tutorial/ch02.py [ln:36-44] !}
```

We will use this in the next chapter when we build the `Order` aggregate.

## Putting It Together

```python
{! docs_src/guides/getting-started/tutorial/ch02.py [ln:70-] !}
```

Run it:

```shell
$ python bookshelf.py
Book: The Great Gatsby
Price: $12.99 USD
Genre: FICTION, Pages: 180
Tags: ['classic', 'american', 'jazz-age']

Money(12.99, USD) == Money(12.99, USD)? True
Money(12.99, USD) == Money(14.99, USD)? False

Address: 123 Main St, Springfield, IL
Country (default): US

Retrieved: The Great Gatsby, $12.99 USD

All checks passed!
```

Notice that the `Money` value object persisted and retrieved correctly —
the repository handles it transparently.

## What We Built

- **Rich field types**: `Text`, `Date`, `Integer`, `Boolean`, `List`, and
  `choices` for constraining values.
- **`Money` value object**: An immutable object that groups amount and
  currency together.
- **`Address` value object**: Ready for use in orders.
- **`ValueObject` field**: Embeds a value object inside an aggregate.

Our Book aggregate now has rich fields and a proper price model. In the
next chapter, we will build the `Order` aggregate with child entities.

## Full Source

```python
{! docs_src/guides/getting-started/tutorial/ch02.py !}
```

## Next

[Chapter 3: Entities and Associations →](03-entities-and-associations.md)
