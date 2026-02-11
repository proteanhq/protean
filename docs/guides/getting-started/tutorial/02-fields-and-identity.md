# Chapter 2: Fields and Identity

In the previous chapter we created a simple `Book` aggregate with a handful
of fields. Now let's explore the full field system — the types available,
the options you can set, and how identity works in Protean.

## Enriching the Book Aggregate

Our Book currently has just `title`, `author`, `isbn`, and `price`. A real
bookstore needs more. Let's add several new fields to demonstrate the range
of types available:

```python
{! docs_src/guides/getting-started/tutorial/ch02.py [ln:1-35] !}
```

We have added:

- **`Text`** for `description` — long-form text, unlike `String` which has a
  `max_length` cap.
- **`Date`** for `publication_date` — a date without time.
- **`Integer`** for `page_count` — whole numbers.
- **`Boolean`** for `in_print` — true/false with a default of `True`.
- **`List`** for `tags` — a list of strings. The `content_type` parameter
  specifies the type of each element.

These cover the most common field types. Protean also provides `DateTime`
(date with time), `Float` (which we already use for `price`), and `Dict`
(key-value pairs). See the
[Fields reference](../../domain-definition/fields/index.md) for the
complete list.

## Field Options

Every field accepts a set of common options:

| Option | Description | Example |
|--------|-------------|---------|
| `required` | Must be provided on creation | `title = String(required=True)` |
| `default` | Value when not provided | `in_print = Boolean(default=True)` |
| `max_length` | Maximum string length | `isbn = String(max_length=13)` |
| `choices` | Restrict to a set of values | `genre = String(choices=Genre)` |

### Constraining with Choices

The `genre` field uses a Python `Enum` to restrict valid values:

```python
{! docs_src/guides/getting-started/tutorial/ch02.py [ln:11-18] !}
```

Attempting to create a book with an invalid genre raises a `ValidationError`:

```python
>>> Book(title="Test", author="Test", genre="ROMANCE")
ValidationError: {'genre': ["Value 'ROMANCE' is not a valid choice. ..."]}
```

Using enums for choices makes your code self-documenting and catches
invalid values at the domain boundary.

### What Happens When Validation Fails

When you provide invalid data — a missing required field, a string
exceeding `max_length`, or an invalid choice — Protean raises a
`ValidationError` with a dictionary mapping field names to error messages:

```python
>>> from protean.exceptions import ValidationError
>>> try:
...     Book(author="Unknown")  # title is required
... except ValidationError as e:
...     print(e.messages)
{'title': ['is required']}
```

Validation happens at creation time, so invalid aggregates never enter
your domain.

## Identity

Every aggregate needs a unique identifier. By default, Protean
auto-generates a UUID string as the `id` field:

```python
>>> book = Book(title="Dune", author="Frank Herbert")
>>> book.id
'a3b2c1d0-e5f6-7890-abcd-ef1234567890'
```

### The Identifier Field

You can also mark a specific field as the identifier using
`identifier=True`:

```python
@domain.aggregate
class Book:
    isbn = String(max_length=13, identifier=True)
    title = String(max_length=200, required=True)
    # ...
```

With this, `isbn` becomes the primary identity — no `id` field is
auto-generated. This is useful when your domain has a natural identity
(like ISBN for books, email for users, etc.).

!!! info "Identity Strategies"
    Protean supports several identity strategies beyond UUID. You can
    configure a custom identity function at the domain level. See the
    [Identity guide](../../essentials/identity.md) for details.

    For this tutorial, we will stick with the default auto-generated
    UUIDs.

## Querying the Repository

In Chapter 1, we used `repo.get(id)` to retrieve a single book. But a
bookstore needs richer queries — searching, filtering, and sorting.

Protean repositories expose a query API through the `_dao` (Data Access
Object):

```python
{! docs_src/guides/getting-started/tutorial/ch02.py [ln:82-101] !}
```

### Key Query Operations

| Operation | Description | Example |
|-----------|-------------|---------|
| `.all()` | Return all records | `repo._dao.query.all()` |
| `.filter(...)` | Filter by field values | `.filter(genre="FICTION")` |
| `.order_by(...)` | Sort results | `.order_by("title")` or `.order_by("-price")` for descending |
| `.first()` | Return first match | `repo._dao.query.filter(author="...").first()` |

The `.all()` method returns a `ResultSet` with a `.total` count and
`.items` list. You can chain operations:

```python
# Fiction books, sorted by price (descending), limited to 5
results = repo._dao.query.filter(genre="FICTION").order_by("-price").limit(5).all()
```

!!! tip "Lookups"
    Filter supports Django-style lookups for comparisons:

    - `price__gte=10.0` — price greater than or equal to 10
    - `page_count__lt=300` — fewer than 300 pages
    - `title__contains="Great"` — title contains "Great"

## Running as a Script

Let's put it all together in a complete runnable script:

```python
{! docs_src/guides/getting-started/tutorial/ch02.py !}
```

Run it:

```shell
$ python bookshelf.py
Retrieved: The Great Gatsby by F. Scott Fitzgerald
Genre: FICTION, Pages: 180
Tags: ['classic', 'american', 'jazz-age']

Total books: 3
Fiction books: 2
  - The Great Gatsby
  - Brave New World

Books alphabetically:
  - Brave New World ($14.99)
  - Sapiens ($18.99)
  - The Great Gatsby ($12.99)

All checks passed!
```

## Summary

In this chapter you learned:

- **Field types**: `String`, `Text`, `Integer`, `Float`, `Boolean`, `Date`,
  `DateTime`, `List`, and `Dict` cover most data modeling needs.
- **Field options**: `required`, `default`, `max_length`, and `choices`
  constrain field values and catch errors early.
- **Identity**: Aggregates get auto-generated UUIDs by default, but you
  can designate any field as the identifier with `identifier=True`.
- **Querying**: The repository's `_dao.query` API supports filtering,
  ordering, and pagination.

Our `Book` aggregate is getting richer, but it still models everything
with primitive fields. In the next chapter, we will introduce **value
objects** — a way to group related fields into meaningful, immutable
concepts like `Money` and `Address`.

## Next

[Chapter 3: Value Objects →](03-value-objects.md)
