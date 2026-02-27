# Repositories

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Repositories provide a collection-oriented interface to persist and retrieve
[aggregates](../domain-definition/aggregates.md). They hide the details of the
underlying storage technology behind a clean, domain-focused API.

Protean automatically provides a default repository for every registered
aggregate. You only need to define a custom repository when you want to add
business-oriented query methods.

## Default repository

Every aggregate gets a default repository out of the box. You access it with
`domain.repository_for()`:

```python
from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class Person:
    name: String(required=True, max_length=50)
    email: String(required=True, max_length=254)
```

```shell
In [1]: repo = domain.repository_for(Person)

In [2]: repo
Out[2]: <PersonRepository at 0x104f3a1d0>
```

The default repository provides these methods:

- **`add(aggregate)`** -- persist or update an aggregate.
- **`get(identifier)`** -- retrieve an aggregate by its identity.
- **`find(criteria)`** -- find all aggregates matching a `Q` expression.
- **`find_by(**kwargs)`** -- find a single aggregate by field values.
- **`exists(criteria)`** -- check if any aggregate matches a `Q` expression.

For basic operations, the default repository is all you need.

## Defining a custom repository

When you need domain-named query methods -- such as finding all overdue
orders or looking up customers by region -- you define a custom repository:

```python hl_lines="16"
--8<-- "guides/change-state/004.py:full"
```

1. The repository is connected to `Person` aggregate through the `part_of`
parameter.

Protean now returns the custom repository whenever you ask for `Person`'s
repository:

```shell hl_lines="3"
In [1]: repo = domain.repository_for(Person)

In [2]: repo
Out[2]: <CustomPersonRepository at 0x1079af290>

In [3]: repo.add(Person(name="John Doe", email="john.doe@example.com"))
Out[3]: <Person: Person object (id: 9ba6a890-e783-455e-9a6b-a0a16c0514df)>

In [4]: repo.find_by_email("john.doe@example.com")
Out[4]: <Person: Person object (id: 9ba6a890-e783-455e-9a6b-a0a16c0514df)>
```

### Multiple domain-named methods

A repository can contain as many query methods as needed. Name them after
the domain concepts they represent:

```python hl_lines="15-27"
--8<-- "guides/change-state/009.py:full"
```

1. The repository is connected to the `Person` aggregate through `part_of`.
2. Custom methods use `self.query` and `self.find_by` to access the persistence layer.

```shell
In [1]: repo = domain.repository_for(Person)

In [2]: repo.adults()
Out[2]: [<Person: Person object (id: ...)>, ...]

In [3]: repo.by_country("CA")
Out[3]: [<Person: Person object (id: ...)>]
```

!!!note
    Methods in the repository should be named for the business queries they
    perform. `adults` is a better name than `filter_by_age_gte_18`. The
    repository should speak the ubiquitous language of the domain.

## Querying inside repositories

Every repository exposes these methods for building queries:

- **`self.query`** -- a [QuerySet](./retrieve-aggregates.md#queryset) for
  building filtered, sorted, paginated queries.
- **`self.find_by(**kwargs)`** -- find a single aggregate matching the given
  fields. Raises `ObjectNotFoundError` if no match is found, and
  `TooManyObjectsError` if multiple matches are found.
- **`self.find(criteria)`** -- find all aggregates matching a `Q` expression.
  Returns a `ResultSet`.
- **`self.exists(criteria)`** -- check if any aggregate matches a `Q`
  expression. Returns `True` or `False`.

```python
from protean.utils.query import Q

@domain.repository(part_of=Person)
class PersonRepository:
    def adults_in_country(self, country_code: str) -> list:
        return self.find(
            Q(age__gte=18, country=country_code)
        ).items

    def find_by_email(self, email: str) -> Person:
        return self.find_by(email=email)

    def has_adults(self) -> bool:
        return self.exists(Q(age__gte=18))
```

Internally, these delegate to the repository's Data Access Object (DAO) --
the layer that talks to the database. The DAO is still accessible as
`self._dao` for advanced use cases, but for typical custom queries,
`self.query`, `self.find`, `self.find_by()`, and `self.exists()` are all you
need.

### Error handling in queries

`get()` and `find_by()` raise exceptions when the expected result is not found:

```python
from protean.exceptions import ObjectNotFoundError, TooManyObjectsError

repo = domain.repository_for(Person)

# Raises ObjectNotFoundError if no aggregate matches the identity
try:
    person = repo.get("nonexistent-id")
except ObjectNotFoundError:
    ...

# Raises ObjectNotFoundError if no match, TooManyObjectsError if multiple
try:
    person = repo.find_by(email="unknown@example.com")
except ObjectNotFoundError:
    ...
```

`exists()` never raises — it returns `True` or `False`:

```python
if repo.exists(Q(email="john@example.com")):
    raise ValueError("Email already taken")
```

For a comprehensive guide on querying, see
[Retrieving Aggregates](./retrieve-aggregates.md).

## Connecting to a specific database

When multiple database providers are configured, you can connect a repository
to a specific one using the `database` parameter:

```python
@domain.repository(part_of=Person, database="reporting")
class PersonReportingRepository:
    def active_users_summary(self) -> list:
        return self.query.filter(active=True).all().items
```

When no `database` is specified, the default value is `"ALL"`, which means
the repository works with whichever provider the aggregate is assigned to
(via the aggregate's `provider` option, which itself defaults to the
`"default"` provider).

!!!note
    A repository can be connected to a specific persistence store by specifying
    the `database` parameter. This is useful when you have separate databases
    for different concerns (e.g., transactional vs. reporting).

## `domain.repository_for()`

`domain.repository_for(AggregateClass)` is the sole entry point for obtaining a
repository instance. It accepts an aggregate class (not a string) and returns
the repository associated with that aggregate:

```python
repo = domain.repository_for(Order)
order = repo.get(order_id)
```

How it works:

- If the aggregate has `is_event_sourced=True`, `repository_for()` returns an
  **event-sourced repository** backed by the event store. The event-sourced
  repository reconstructs aggregate state by replaying events from the
  aggregate's stream — it does not read from a database table.

- Otherwise, it returns the aggregate's database-backed repository (custom if
  one is registered, default if not).

This routing is transparent — you always call `domain.repository_for()` the
same way, and Protean returns the correct repository based on the aggregate's
configuration.

## Why there is no `delete` or `remove`

Repositories intentionally do not provide a `delete()` or `remove()` method.

In Domain-Driven Design, "deleting" a business entity is almost always a
**state transition**, not a record erasure. An order is *cancelled*, a user is
*deactivated*, a subscription is *archived*. These transitions are meaningful
domain events that should be modeled explicitly — with commands, aggregate
methods, and events — not hidden behind a database `DELETE`.

For infrastructure-level record removal (projection rebuilds, test teardown,
GDPR right-to-erasure compliance), you can access the underlying DAO directly:

```python
repo = domain.repository_for(Person)
repo._dao.delete(person)
```

This is an intentional escape hatch, not a recommended domain operation. Use it
only when the domain model does not apply (e.g., cleaning up test data).

## Transactions and Unit of Work

Every call to `repository.add()` participates in the enclosing
[Unit of Work](./unit-of-work.md). Inside a command handler or `@use_case`
method, this happens automatically — changes are committed when the handler
completes, or rolled back if an exception is raised.

Outside a handler (e.g., in a shell session or script), `add()` creates a
temporary UoW, commits immediately, and discards it.

## When to define a custom repository

Define a custom repository when you need to:

- **Express domain queries** -- methods like `overdue_orders()` or
  `customers_in_region(region)` that encapsulate business-oriented queries.
- **Compose complex queries** -- queries involving
  [Q objects](./retrieve-aggregates.md#complex-queries-with-q-objects),
  multiple filters, or specific ordering.
- **Use raw queries** -- database-specific queries that cannot be expressed
  through the QuerySet API.

You do **not** need a custom repository for:

- Basic `add` and `get` operations -- the default repository handles these.
- One-off queries in command handlers or application services -- consider
  adding a named method to a custom repository instead.

!!!note
    Keep repositories thin. They should contain query logic, not business
    logic. If a retrieval method starts making decisions or enforcing rules,
    that logic belongs in the aggregate or a
    [domain service](../domain-behavior/domain-services.md).

---

!!! tip "See also"
    **Concept overview:** [Repositories](../../concepts/building-blocks/repositories.md) — The role of repositories in DDD and how Protean implements the pattern.

    **Related guides:**

    - [Retrieving Aggregates](./retrieve-aggregates.md) — QuerySets, filtering, Q objects, and pagination.
    - [Persist Aggregates](./persist-aggregates.md) — Save and update aggregates through repositories.
    - [Unit of Work](./unit-of-work.md) — Transaction management and commit lifecycle.
