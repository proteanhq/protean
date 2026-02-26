# Retrieve Aggregates

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

An aggregate can be retrieved with the repository's `get` method, if you know
its identity:

```python hl_lines="16 20"
--8<-- "guides/change-state/001.py:full"
```

1.  Identity is explicitly set to **1**.

```shell hl_lines="1"
In [1]: domain.repository_for(Person).get("1")
Out[1]: <Person: Person object (id: 1)>
```

`get` raises `ObjectNotFoundError` if no aggregate is found with the given
identity.

Finding an aggregate by a field value is also possible, but requires a custom
repository to be defined with a business-oriented method. See the
[Repositories](./repositories.md) guide for details on defining custom
repositories.

## Querying beyond `get`

Beyond `get`, every repository exposes convenience methods for querying:

- **`.query`** -- returns a QuerySet for building filtered, sorted, paginated
  queries.
- **`.find_by(**kwargs)`** -- finds a single aggregate matching the given
  field values.
- **`.find(criteria)`** -- finds all aggregates matching a `Q` criteria
  expression. Returns a `ResultSet`.
- **`.exists(criteria)`** -- checks if any aggregate matches a `Q` criteria
  expression. Returns `True` or `False` without loading objects.

These are available both on the repository instance returned by
`domain.repository_for()` and inside custom repository methods via `self`.

## Sample data

For the purposes of this guide, assume that the following `Person` aggregates
exist in the database:

```python hl_lines="7-11"
--8<-- "guides/change-state/005.py:full"
```

```shell
In [1]: repository = domain.repository_for(Person)

In [2]: for person in [
   ...:     Person(name="John Doe", age=38, country="CA"),
   ...:     Person(name="John Roe", age=41, country="US"),
   ...:     Person(name="Jane Doe", age=36, country="CA"),
   ...:     Person(name="Baby Doe", age=3, country="CA"),
   ...:     Person(name="Boy Doe", age=8, country="CA"),
   ...:     Person(name="Girl Doe", age=11, country="CA"),
   ...: ]:
   ...:     repository.add(person)
   ...:
```

All queries below can be placed in
[custom repository methods](./repositories.md#defining-a-custom-repository).

## Finding a single aggregate

### `find_by`

Use `find_by` when you want to find a single aggregate matching one or more
field values:

```shell
In [1]: person = repository.find_by(age=36, country="CA")

In [2]: person.name
Out[2]: 'Jane Doe'
```

`find_by` raises `ObjectNotFoundError` if no aggregates are found, and
`TooManyObjectsError` when more than one aggregate matches.

### `find`

Use `find` to retrieve all aggregates matching a `Q` criteria expression.
It accepts composable `Q` objects and returns a `ResultSet`:

```python
from protean.utils.query import Q
```

```shell
In [1]: results = repository.find(Q(country="CA"))

In [2]: results.total
Out[2]: 5

In [3]: [p.name for p in results.items]
Out[3]: ['John Doe', 'Jane Doe', 'Baby Doe', 'Boy Doe', 'Girl Doe']
```

`find` is especially useful with composed criteria:

```shell
In [1]: results = repository.find(Q(country="CA") & Q(age__gte=18))

In [2]: [p.name for p in results.items]
Out[2]: ['John Doe', 'Jane Doe']
```

See [Composable Query Functions](#composable-query-functions) below for
using `find()` with reusable, domain-named query criteria.

### `exists`

Use `exists` to check whether matching aggregates exist without loading them:

```shell
In [1]: repository.exists(Q(country="US"))
Out[1]: True

In [2]: repository.exists(Q(country="UK"))
Out[2]: False
```

`exists` also accepts composed criteria:

```python
# Inside a custom repository method
def has_adults_in_country(self, country: str) -> bool:
    return self.exists(Q(age__gte=18) & Q(country=country))
```

---

## QuerySet

!!! tip "Querying projections?"
    For projection queries, use `domain.view_for(ProjectionClass).query` instead.
    It returns a `ReadOnlyQuerySet` that enforces CQRS read-only access.
    See [Querying Projections](../consume-state/projections.md#querying-projections).

A QuerySet represents a collection of objects from your database that can be
filtered, ordered, and paginated. You access a QuerySet through the
repository's `.query` property:

```python
queryset = repository.query
```

QuerySets are **lazy** -- they don't access the database until you actually
need the data. This allows you to chain multiple operations efficiently
without hitting the database repeatedly. Each method returns a new QuerySet
clone, leaving the original unchanged.

### `filter` and `exclude`

`filter` narrows down the query results based on specified conditions.
Multiple keyword arguments are ANDed together:

```shell
In [1]: people = repository.query.filter(age__gte=18, country="CA").all().items

In [2]: [person.name for person in people]
Out[2]: ['John Doe', 'Jane Doe']
```

`exclude` removes matching objects from the queryset:

```shell
In [1]: people = repository.query.exclude(country="US").all().items

In [2]: [person.name for person in people]
Out[2]: ['John Doe', 'Jane Doe', 'Baby Doe', 'Boy Doe', 'Girl Doe']
```

### Chaining operations

One of the most powerful features of QuerySets is the ability to chain
operations. Each chained call returns a new QuerySet -- the original is never
modified:

```shell
In [1]: adults_in_ca = repository.query.filter(age__gte=18).filter(country="CA").order_by("name").all().items

In [2]: [f"{person.name}, {person.age}" for person in adults_in_ca]
Out[2]: ['Jane Doe, 36', 'John Doe, 38']
```

### Using QuerySets in repository methods

In a real application, you would wrap QuerySet operations in repository
methods with domain-meaningful names:

```python hl_lines="5-7 10-12"
@domain.repository(part_of=Person)
class PersonRepository:
    def adults_in_country(self, country_code):
        """Find all adults in the specified country."""
        return self.query.filter(
            age__gte=18, country=country_code).all().items

    def children_by_age(self, country_code=None):
        """Find all children ordered by age."""
        query = self.query.filter(age__lt=18)
        if country_code:
            query = query.filter(country=country_code)
        return query.order_by("age").all().items
```

## Filtering criteria

Queries use lookup suffixes appended to field names with double underscores
(`__`) to express comparison operators. When no suffix is used, `exact` match
is assumed.

- **`exact`** -- match exact value (default when no suffix is used)
- **`iexact`** -- case-insensitive exact match
- **`contains`** -- substring containment (case-sensitive)
- **`icontains`** -- substring containment (case-insensitive)
- **`gt`** -- greater than
- **`gte`** -- greater than or equal to
- **`lt`** -- less than
- **`lte`** -- less than or equal to
- **`in`** -- value is in a given list
- **`any`** -- any of given values matches items in a list field

```shell
In [1]: repository.query.filter(name__contains="Doe").all().total
Out[1]: 5

In [2]: repository.query.filter(age__gt=10, age__lt=40).all().total
Out[2]: 3

In [3]: repository.query.filter(name__in=["John Doe", "Jane Doe"]).all().total
Out[3]: 2
```

!!!note
    These lookups have database-specific implementations. Refer to your chosen
    adapter's documentation for supported filtering criteria.

---

## Complex queries with Q objects

For queries that require OR conditions or negation, use Q objects from
`protean.utils.query`:

```python
from protean.utils.query import Q
```

### AND

Combine Q objects with `&` to require all conditions:

```python
# People named "Doe" who are at least 18
people = repository.query.filter(
    Q(name__contains="Doe") & Q(age__gte=18)
).all().items
```

This is equivalent to passing multiple keyword arguments to `filter()`, since
keyword arguments are ANDed together by default.

### OR

Combine Q objects with `|` to match any condition:

```python
# People who are under 5 OR over 40
people = repository.query.filter(
    Q(age__lt=5) | Q(age__gt=40)
).all().items
```

### NOT

Negate a Q object with `~` to exclude matching records:

```python
# Everyone except those in the US
people = repository.query.filter(
    ~Q(country="US")
).all().items
```

### Nesting

Q objects can be combined and nested to express complex criteria:

```python
# (Adults in CA) OR (children in US)
people = repository.query.filter(
    (Q(age__gte=18) & Q(country="CA")) | (Q(age__lt=18) & Q(country="US"))
).all().items
```

### Mixing Q objects with keyword arguments

Q objects can be mixed with keyword arguments in `filter()`. The Q objects
and keyword arguments are ANDed together:

```python
# People in CA who are either named "John Doe" or under age 5
people = repository.query.filter(
    Q(name="John Doe") | Q(age__lt=5), country="CA"
).all().items
```

## Composable query functions

When the same filter criteria appears in multiple places -- a command handler,
an event handler, a projector, a scheduled job -- you can extract it into a
plain Python function that returns a `Q` object. This gives you named,
reusable, composable query criteria without any framework overhead:

```python
from protean.utils.query import Q
from datetime import datetime, timedelta
from decimal import Decimal


def overdue_orders(grace_days: int = 0) -> Q:
    """Orders past their payment deadline."""
    deadline = datetime.now() - timedelta(days=grace_days)
    return Q(status="pending", due_date__lt=deadline)


def high_value_orders(min_amount: Decimal = Decimal("1000")) -> Q:
    """Orders exceeding a monetary threshold."""
    return Q(total__gte=min_amount)


def in_region(region: str) -> Q:
    """Orders shipping to a specific region."""
    return Q(shipping_region=region)
```

These functions compose naturally with `&`, `|`, and `~`:

```python
repo = domain.repository_for(Order)

# Find all overdue orders
overdue = repo.find(overdue_orders())

# Compose: overdue AND high-value
critical = repo.find(overdue_orders(grace_days=3) & high_value_orders(5000))

# Compose: high-value in a specific region
regional = repo.find(high_value_orders() & in_region("US"))

# Negate: orders that are NOT recent
stale = repo.find(~recent_orders(within_days=7))

# Check existence
if repo.exists(overdue_orders() & high_value_orders(5000)):
    trigger_escalation()
```

The same functions work with the QuerySet API when you need ordering or
pagination:

```python
results = (
    repo.query
    .filter(overdue_orders() & in_region("US"))
    .order_by("-total")
    .limit(20)
    .all()
)
```

And inside custom repository methods:

```python
@domain.repository(part_of=Order)
class OrderRepository:
    def critical_orders(self) -> list:
        return self.find(
            overdue_orders(grace_days=3) & high_value_orders(5000)
        ).items

    def has_overdue_in_region(self, region: str) -> bool:
        return self.exists(overdue_orders() & in_region(region))
```

This pattern gives you most of the formal
[Specification Pattern](https://martinfowler.com/apsupp/spec.pdf)'s value --
named, composable, testable query criteria -- with zero framework complexity.
The Q functions are regular Python: easy to write, easy to test, and easy to
understand.

### Structuring as specifications

When you need both database queries *and* in-memory evaluation of the same
business rule -- for example, querying overdue orders from the database and
also checking whether a single order is overdue inside an event handler --
you can structure your query criteria as specification classes:

```python
from abc import ABC, abstractmethod
from protean.utils.query import Q


class Specification(ABC):
    """Base class for domain query specifications."""

    @abstractmethod
    def to_query(self) -> Q:
        """Return Q criteria for database queries."""
        ...

    @abstractmethod
    def is_satisfied_by(self, entity) -> bool:
        """Test whether an entity matches this rule in memory."""
        ...

    def __and__(self, other: "Specification") -> "Specification":
        return _And(self, other)

    def __or__(self, other: "Specification") -> "Specification":
        return _Or(self, other)

    def __invert__(self) -> "Specification":
        return _Not(self)


class _And(Specification):
    def __init__(self, left, right):
        self.left, self.right = left, right

    def to_query(self) -> Q:
        return self.left.to_query() & self.right.to_query()

    def is_satisfied_by(self, entity) -> bool:
        return self.left.is_satisfied_by(entity) and self.right.is_satisfied_by(entity)


class _Or(Specification):
    def __init__(self, left, right):
        self.left, self.right = left, right

    def to_query(self) -> Q:
        return self.left.to_query() | self.right.to_query()

    def is_satisfied_by(self, entity) -> bool:
        return self.left.is_satisfied_by(entity) or self.right.is_satisfied_by(entity)


class _Not(Specification):
    def __init__(self, spec):
        self.spec = spec

    def to_query(self) -> Q:
        return ~self.spec.to_query()

    def is_satisfied_by(self, entity) -> bool:
        return not self.spec.is_satisfied_by(entity)
```

With this base class in place, define concrete specifications for your
domain:

```python
class OverdueOrders(Specification):
    def __init__(self, grace_days: int = 0):
        self.grace_period = timedelta(days=grace_days)

    def to_query(self) -> Q:
        deadline = datetime.now() - self.grace_period
        return Q(status="pending", due_date__lt=deadline)

    def is_satisfied_by(self, order) -> bool:
        deadline = datetime.now() - self.grace_period
        return order.status == "pending" and order.due_date < deadline


class HighValueOrders(Specification):
    def __init__(self, min_amount: Decimal = Decimal("1000")):
        self.min_amount = min_amount

    def to_query(self) -> Q:
        return Q(total__gte=self.min_amount)

    def is_satisfied_by(self, order) -> bool:
        return order.total >= self.min_amount
```

Use `to_query()` with `find()` for database queries, and
`is_satisfied_by()` for in-memory checks:

```python
# Database query
critical = OverdueOrders(grace_days=3) & HighValueOrders(min_amount=5000)
results = repo.find(critical.to_query())

# In-memory check (no database hit)
if OverdueOrders().is_satisfied_by(order):
    send_reminder(order)
```

!!! tip
    Start with plain Q-returning functions. Graduate to specification
    classes only when you genuinely need `is_satisfied_by()` for in-memory
    evaluation alongside database queries.

## Sorting results

Use `order_by()` to sort results by one or more fields. Prefix a field name
with `-` for descending order:

```shell
In [1]: people = repository.query.order_by("-age").all().items

In [2]: [(person.name, person.age) for person in people]
Out[2]:
[('John Roe', 41),
 ('John Doe', 38),
 ('Jane Doe', 36),
 ('Girl Doe', 11),
 ('Boy Doe', 8),
 ('Baby Doe', 3)]
```

You can sort by multiple fields by passing a list:

```python
# Sort by country ascending, then age descending
people = repository.query.order_by(["country", "-age"]).all().items
```

## Pagination

### Controlling result size

By default, Protean limits the number of records returned by a query to 100.
You can control this behavior in several ways.

**Setting a default limit during element registration:**

```python hl_lines="2"
@domain.aggregate(limit=50)
class Person:
    # Queries will return at most 50 records by default
    id = field.Integer(identifier=True)
    name = field.String(required=True, max_length=50)
```

Setting the limit to `None` removes the limit entirely.

**Applying a limit at query time:**

```python
# Limit to 10 records
limited_query = repository.query.limit(10).all()

# Remove limit entirely
unlimited_query = repository.query.limit(None).all()
```

!!!note
    A limit set during element registration becomes the default for all
    queries on that element. You can always override it at query time using
    `limit()`.

### Limit and offset

Combine `limit` with `offset` for pagination:

```python
def get_page(self, page_number, page_size=10):
    """Get a specific page of results."""
    offset = (page_number - 1) * page_size
    return self.query.offset(offset).limit(page_size).all()
```

### Pagination navigation

The result provides pagination properties for navigating through pages:

```python
result = repository.query.offset(10).limit(10).all()

result.page        # Current page number (1-indexed)
result.page_size   # Number of items per page (alias for limit)
result.total_pages # Total number of pages
result.has_next    # True if more pages exist beyond the current one
result.has_prev    # True if this is not the first page
```

## Evaluating a QuerySet

A QuerySet is lazy -- it does not hit the database until it is **evaluated**.
Evaluation is triggered when you:

- Call **`.all()`** -- returns a ResultSet
- **Iterate**: `for person in queryset: ...`
- Check **length**: `len(queryset)`
- Check **truthiness**: `bool(queryset)` or `if queryset: ...`
- **Slice**: `queryset[0]` or `queryset[0:5]`
- Check **containment**: `person in queryset`
- Access **properties**: `.total`, `.items`, `.first`, `.last`, `.has_next`,
  `.has_prev`, `.page`, `.page_size`, `.total_pages`

Once evaluated, results are cached internally. Call `.all()` again to force
a fresh database query.

### QuerySet properties

These properties are available on the QuerySet itself and trigger evaluation
on first access:

- **`total`** -- total count of matching records (int)
- **`items`** -- list of result entity objects
- **`first`** -- first result, or `None` if empty
- **`last`** -- last result, or `None` if empty
- **`has_next`** -- `True` if more pages exist
- **`has_prev`** -- `True` if previous pages exist
- **`page`** -- current page number (1-indexed, int)
- **`page_size`** -- items per page, or `None` when unlimited (alias for `limit`)
- **`total_pages`** -- total number of pages (0 when no results)

```shell
In [1]: query = repository.query.filter(country="CA").order_by("age")

In [2]: query.total
Out[2]: 5

In [3]: query.first.name
Out[3]: 'Baby Doe'

In [4]: query.last.name
Out[4]: 'John Doe'
```

## Bulk operations

QuerySets provide methods for updating and deleting multiple records at once.

### `update`

Updates each matching object individually -- loads every entity and triggers
callbacks and validations:

```python
count = repository.query.filter(country="CA", age__lt=18).update(country="XX")
```

Returns the number of objects matched.

### `update_all`

Sends the update directly to the database without loading entities:

```python
count = repository.query.filter(country="CA", age__lt=18).update_all(country="XX")
```

Returns the number of objects matched.

!!! warning
    `update_all` bypasses entity instantiation, callbacks, and validations.
    Use it only when you are certain no business logic needs to run during
    the operation.

### `delete`

Deletes each matching object individually -- loads every entity first:

```python
count = repository.query.filter(country="XX").delete()
```

Returns the number of objects deleted.

### `delete_all`

Sends the delete directly to the database without loading entities:

```python
count = repository.query.filter(country="XX").delete_all()
```

Returns the number of objects deleted.

!!! warning
    `delete_all` bypasses entity instantiation, callbacks, and validations.
    Use it only when you are certain no business logic needs to run during
    the operation.

## ResultSet

The `.all()` method returns a `ResultSet` instance. This class prevents
DAO-specific data structures from leaking into the domain layer.

### Attributes

- **`offset`** -- the current offset (zero-indexed)
- **`limit`** -- the number of items requested
- **`total`** -- total number of items matching the query (across all pages)
- **`items`** -- list of result entity objects in the current page

### Properties

- **`first`** -- first item, or `None` if empty
- **`last`** -- last item, or `None` if empty
- **`has_next`** -- `True` if more pages exist beyond the current one
- **`has_prev`** -- `True` if this is not the first page
- **`page`** -- current page number (1-indexed)
- **`page_size`** -- number of items per page (alias for `limit`; `None` when unlimited)
- **`total_pages`** -- total number of pages (0 when no results)

### Methods

- **`to_dict()`** -- returns the result as a dictionary with `offset`,
  `limit`, `total`, `page`, `page_size`, `total_pages`, `has_next`,
  `has_prev`, and `items` keys.

A ResultSet also supports `bool()` (truthy if items exist), `iter()` (iterate
over items), and `len()` (number of items in the current page, not the total).

```shell
In [1]: result = repository.query.all()

In [2]: result
Out[2]: <ResultSet: 6 items>

In [3]: result.to_dict()
Out[3]:
{'offset': 0,
 'limit': 1000,
 'total': 6,
 'items': [<Person: Person object (id: 84cac5ae-8272-4936-aa45-9342abe05513)>,
  <Person: Person object (id: aec03bb7-a97d-4722-9e10-fa5c324aa69b)>,
  <Person: Person object (id: 0b6314e9-e9b0-4456-bf04-1b0e05af1bf2)>,
  <Person: Person object (id: 1be4b9cd-deb0-4c07-bdfc-b2dba119f7a0)>,
  <Person: Person object (id: c5730eb0-9638-4d9d-8617-c2b3270be859)>,
  <Person: Person object (id: 4683a592-ffd5-4f01-84bc-02401c785922)>]}
```

## Raw queries

For database-specific queries that cannot be expressed through the QuerySet
API, use `raw()`:

```python
results = repository.query.raw('{"name": "John Doe", "age__gte": 18}')
```

The query format is database-specific -- a JSON string for the memory adapter,
SQL for SQLAlchemy, etc. All other query options (`order_by`, `offset`,
`limit`) are ignored for raw queries.

!!! warning
    Raw queries bypass Protean's query abstraction and are tied to a specific
    database technology. Use them sparingly and only when the QuerySet API
    cannot express your query.

---

!!! tip "See also"
    **Concept overview:** [Repositories](../../concepts/building-blocks/repositories.md) — The role of repositories in DDD and how Protean implements the pattern.

    **Related guides:**

    - [Repositories](./repositories.md) — Define custom repositories with domain-named query methods.
    - [Persist Aggregates](./persist-aggregates.md) — Save and update aggregates through repositories.
