# Repositories

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


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

The default repository provides two methods:

- **`add(aggregate)`** -- persist or update an aggregate.
- **`get(identifier)`** -- retrieve an aggregate by its identity.

For basic CRUD operations, the default repository is all you need.

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

Every repository exposes two convenience methods for building queries:

- **`self.query`** -- a [QuerySet](./retrieve-aggregates.md#queryset) for
  building filtered, sorted, paginated queries.
- **`self.find_by(**kwargs)`** -- find a single aggregate matching the given
  fields. Raises `ObjectNotFoundError` if no match is found, and
  `TooManyObjectsError` if multiple matches are found.

```python
@domain.repository(part_of=Person)
class PersonRepository:
    def adults_in_country(self, country_code: str) -> list:
        return self.query.filter(
            age__gte=18, country=country_code
        ).all().items

    def find_by_email(self, email: str) -> Person:
        return self.find_by(email=email)
```

Internally, these delegate to the repository's Data Access Object (DAO) --
the layer that talks to the database. The DAO is still accessible as
`self._dao` for advanced use cases (e.g. `exists()`, `outside_uow()`), but
for typical custom queries, `self.query` and `self.find_by()` are all you
need.

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

When no `database` is specified, the repository uses the `default` provider.

!!!note
    A repository can be connected to a specific persistence store by specifying
    the `database` parameter. This is useful when you have separate databases
    for different concerns (e.g., transactional vs. reporting).

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
