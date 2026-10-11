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

- **`.query`**: Returns a QuerySet for building filtered, sorted, paginated
  queries.
- **`.find_by(**kwargs)`**: finds a single aggregate matching the given
  field values.
- **`.find(criteria)`**: Finds all aggregates matching a `Q` criteria
  expression. Returns a `ResultSet`.
- **`.exists(criteria)`**: Checks if any aggregate matches a `Q` criteria
  expression. Returns `True` or `False`.

These are available both on the repository instance returned by
`domain.repository_for()` and inside custom repository methods via `self`.

## Sample data

For the purposes of this guide, assume that the following `Person` aggregates
exist in the database:

```python hl_lines="7-11"
--8<-- "guides/change-state/005.py:full"
```

The code below activates the domain and adds six people. The examples on this
page query this data:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:seed"
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
--8<-- "guides/change-state/retrieve-aggregates/001.py:import_q"
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

Use `exists` to check whether any aggregate matches. It runs the same query as
`find` and checks whether any rows came back, so it still reads the matching
aggregates:

```shell
In [1]: repository.exists(Q(country="US"))
Out[1]: True

In [2]: repository.exists(Q(country="UK"))
Out[2]: False
```

`exists` also accepts composed criteria:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:exists_method"
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
--8<-- "guides/change-state/retrieve-aggregates/001.py:queryset"
```

QuerySets are **lazy**. They don't access the database until you actually need
the data. This allows you to chain multiple operations efficiently without
hitting the database repeatedly. Each method returns a new QuerySet clone,
leaving the original unchanged.

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

QuerySets can chain operations. Each chained call returns a new QuerySet. The
original is never modified:

```shell
In [1]: adults_in_ca = repository.query.filter(age__gte=18).filter(country="CA").order_by("name").all().items

In [2]: [f"{person.name}, {person.age}" for person in adults_in_ca]
Out[2]: ['Jane Doe, 36', 'John Doe, 38']
```

### Using QuerySets in repository methods

In a real application, you would wrap QuerySet operations in repository
methods with domain-meaningful names:

```python hl_lines="5 9-12"
--8<-- "guides/change-state/retrieve-aggregates/001.py:repository"
```

## Filtering criteria

Queries use lookup suffixes appended to field names with double underscores
(`__`) to express comparison operators. When no suffix is used, `exact` match
is assumed.

- **`exact`**: Match exact value (default when no suffix is used)
- **`iexact`**: Case-insensitive exact match
- **`contains`**: Substring containment (case-sensitive)
- **`icontains`**: Substring containment (case-insensitive)
- **`startswith`**: Starts with a given prefix
- **`endswith`**: Ends with a given suffix
- **`gt`**: Greater than
- **`gte`**: Greater than or equal to
- **`lt`**: Less than
- **`lte`**: Less than or equal to
- **`in`**: Value is in a given list
- **`isnull`**: Field is null (`True`) or not null (`False`)
- **`any`**: A list field contains any of the given values
- **`overlap`**: A list field shares any element with the given list

```shell
In [1]: repository.query.filter(name__contains="Doe").all().total
Out[1]: 5

In [2]: repository.query.filter(age__gt=10, age__lt=40).all().total
Out[2]: 3

In [3]: repository.query.filter(name__in=["John Doe", "Jane Doe"]).all().total
Out[3]: 2
```

The `isnull` lookup is handy for fields that may be unset:

```python
--8<-- "guides/change-state/retrieve-aggregates/002.py:article"

--8<-- "guides/change-state/retrieve-aggregates/002.py:isnull"
```

### Comparing two fields with `F`

By default the right-hand side of a lookup is a literal value. To compare one
field against **another field of the same aggregate**, wrap the other field's
name in `F`:

```python
--8<-- "guides/change-state/retrieve-aggregates/002.py:import_f"
--8<-- "guides/change-state/retrieve-aggregates/002.py:notification"

--8<-- "guides/change-state/retrieve-aggregates/002.py:field_reference"
```

`F` works with any comparison lookup (`exact`, `gt`, `gte`, `lt`, `lte`). The
comparison is evaluated at the database, so no rows are fetched only to be
discarded in Python. Only a bare field reference is supported: arithmetic
(`F("a") + 1`) and functions are not.

!!!note
    The in-memory and SQLAlchemy adapters resolve `F` to the referenced column.
    The Elasticsearch adapter raises `NotImplementedError` for `F`-bearing
    predicates, since column-to-column comparison there would need a script
    query.

!!!note
    These lookups have database-specific implementations, and a few (the array
    lookups `any` / `overlap`, and `F()`) are not supported on every adapter. See
    the [lookup support matrix](../../concepts/internals/query-system.md#lookup-support-across-adapters)
    for which adapter supports what; an unsupported lookup raises
    `NotImplementedError` rather than returning wrong results.

---

## Complex queries with Q objects

For queries that require OR conditions or negation, use Q objects from
`protean.utils.query`:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:import_q"
```

### AND

Combine Q objects with `&` to require all conditions:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:q_and"
```

This is equivalent to passing multiple keyword arguments to `filter()`, since
keyword arguments are ANDed together by default.

### OR

Combine Q objects with `|` to match any condition:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:q_or"
```

### NOT

Negate a Q object with `~` to exclude matching records:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:q_not"
```

### Nesting

Q objects can be combined and nested to express complex criteria:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:q_nested"
```

### Mixing Q objects with keyword arguments

Q objects can be mixed with keyword arguments in `filter()`. The Q objects
and keyword arguments are ANDed together:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:q_mixed"
```

## Composable query functions

When the same filter criteria appears in multiple places (a command handler, an
event handler, a projector, a scheduled job) you can extract it into a plain
Python function that returns a `Q` object. This gives you named, reusable,
composable query criteria without any framework overhead:

```python
--8<-- "guides/change-state/retrieve-aggregates/003.py:import_q"
--8<-- "guides/change-state/retrieve-aggregates/003.py:import_datetime"
--8<-- "guides/change-state/retrieve-aggregates/003.py:functions"
```

These functions compose naturally with `&`, `|`, and `~`:

```python
--8<-- "guides/change-state/retrieve-aggregates/003.py:compose"
```

The same functions work with the QuerySet API when you need ordering or
pagination:

```python
--8<-- "guides/change-state/retrieve-aggregates/003.py:queryset"
```

And inside custom repository methods:

```python
--8<-- "guides/change-state/retrieve-aggregates/003.py:repository"
```

This pattern gives you most of the formal [Specification
Pattern](https://martinfowler.com/apsupp/spec.pdf)'s value (named, composable,
testable query criteria) with zero framework complexity. The Q functions are
regular Python: easy to write, easy to test, and easy to understand.

### Structuring as specifications

When you need both database queries *and* in-memory evaluation of the same
business rule, for example, querying overdue orders from the database and also
checking whether a single order is overdue inside an event handler. You can
structure your query criteria as specification classes:

```python
--8<-- "guides/change-state/retrieve-aggregates/003.py:import_abc"
--8<-- "guides/change-state/retrieve-aggregates/003.py:import_q"
--8<-- "guides/change-state/retrieve-aggregates/003.py:specification"
```

With this base class in place, define concrete specifications for your
domain:

```python
--8<-- "guides/change-state/retrieve-aggregates/003.py:concrete_specifications"
```

Use `to_query()` with `find()` for database queries, and
`is_satisfied_by()` for in-memory checks:

```python
--8<-- "guides/change-state/retrieve-aggregates/003.py:use_specifications"
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
--8<-- "guides/change-state/retrieve-aggregates/001.py:order_by_fields"
```

## Pagination

### Controlling result size

By default, Protean limits the number of records returned by a query to 100.
You can control this behavior in several ways.

**Setting a default limit during element registration:**

```python hl_lines="1"
--8<-- "guides/change-state/retrieve-aggregates/004.py:limit"
```

Setting the limit to `None` removes the limit entirely.

**Applying a limit at query time:**

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:limit"
```

!!!note
    A limit set during element registration becomes the default for all
    queries on that element. You can always override it at query time using
    `limit()`.

### Limit and offset

Combine `limit` with `offset` for pagination:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:get_page"
```

### Pagination navigation

The result provides pagination properties for navigating through pages:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:pagination"
```

## Evaluating a QuerySet

A QuerySet is lazy. It does not hit the database until it is **evaluated**.
Evaluation is triggered when you:

- Call **`.all()`**, returns a ResultSet
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

- **`total`**: Total count of matching records (int)
- **`items`**: List of result entity objects
- **`first`**: First result, or `None` if empty
- **`last`**: Last result, or `None` if empty
- **`has_next`**: `True` if more pages exist
- **`has_prev`**: `True` if this page has items and is not the first page
- **`page`**: Current page number (1-indexed, int)
- **`page_size`**: Items per page, or `None` when unlimited (alias for `limit`)
- **`total_pages`**: Total number of pages (0 when no results)

```shell
In [1]: query = repository.query.filter(country="CA").order_by("age")

In [2]: query.total
Out[2]: 5

In [3]: query.first.name
Out[3]: 'Baby Doe'

In [4]: query.last.name
Out[4]: 'John Doe'
```

## Counting matches

When you only need *how many* records match, `count()` issues a single
`SELECT COUNT(*)` (or the adapter's equivalent) without projecting columns or
materializing entities:

```shell
In [1]: repository.query.filter(country="CA").count()
Out[1]: 5
```

`count()` ignores `offset`, `limit`, and `order_by`, since none of them affect
the number of matching rows. Prefer it over `len(queryset)` or `.all().total`
when you don't need the rows themselves: those evaluate the full query and
build entity objects, while `count()` asks the database for the number alone.

### Fetching items without a total

`all()` normally reports both the page of `items` and the `total` count of
matching rows. On some adapters (SQLAlchemy) the total requires a second
`COUNT` round-trip. When you only need the items and can disregard
`ResultSet.total`, pass `with_total=False` to skip that round-trip:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:with_total"
```

With `with_total=False`, the memory and SQLAlchemy adapters set `total` to the
number of items on the page. Elasticsearch returns the full count with every
search, so it still sets `total` to the number of matching rows.

## Projecting fields with `only`

When you need a few columns rather than whole aggregates, `only()` restricts
the query to the named fields (the identifier is always included) and returns
read-only `Record` objects instead of fully materialized entities:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:only"
```

```shell
In [1]: record = repository.query.only("name").all().first
In [2]: record.name
Out[2]: 'John Doe'
In [3]: record.id          # identifier is always projected
Out[3]: '8c2e...'
In [4]: record["name"]     # item access works too
Out[4]: 'John Doe'
```

This avoids loading large columns (JSON blobs, long text) on read-optimized
paths such as cleanups, exports, and per-field statistics. Each adapter prunes
the fetch natively: SQLAlchemy with `load_only`, Elasticsearch with `_source`
filtering, and the in-memory store when it builds the result.

A `Record` is intentionally **not** a domain entity. It carries no behavior,
runs no invariants, and cannot be saved. Reading a field that was not projected
raises an error rather than returning a silent `None`, so a missing projection
is never mistaken for a null value:

```python
# fragment
record = repository.query.only("name").all().first
record.age          # AttributeError: 'age' was not projected
record.name = "X"   # NotSupportedError: Records are read-only
```

Because a `Record` is not an entity, `only()` cannot be combined with the
entity-loading operations `update()` and `delete()`; both raise
`NotSupportedError`. `count()` works with `only()` (the projection is moot for a
count), and `raw()` ignores any projection and always returns full entities.

Calling `only()` again replaces the projection (projections do not compose);
calling it with no arguments clears the projection and restores full-entity
loading. See the [QuerySet API reference](../../api/queryset.md) for the full
`Record` surface.

## Bulk operations

QuerySets provide methods for updating and deleting multiple records at once.

### `update`

!!! warning "Deprecated in 0.18.0, removed in 1.0.0"
    `update()` patches fields straight onto the store, so the change never goes
    through a behaviour method on the aggregate and the events that change
    should raise never fire. Calling it emits a `RemovedInProtean10Warning`.
    Load each match, invoke a behaviour method on it, and persist it with
    `repository.add()`. See the
    [migration note](../../reference/migration/v0-18.md#daoupdate-and-querysetupdate-are-deprecated).

Updates each matching object individually: it loads every entity and triggers
callbacks and validations:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:update"
```

Returns the number of objects matched.

### `delete`

Deletes each matching object individually: it loads every entity first:

```python
--8<-- "guides/change-state/retrieve-aggregates/001.py:delete"
```

Returns the number of objects deleted.

## ResultSet

The `.all()` method returns a `ResultSet` instance. This class prevents
DAO-specific data structures from leaking into the domain layer.

### Attributes

- **`offset`**: The current offset (zero-indexed)
- **`limit`**: The number of items requested
- **`total`**: Total number of items matching the query (across all pages)
- **`items`**: List of result entity objects in the current page

### Properties

- **`first`**: First item, or `None` if empty
- **`last`**: Last item, or `None` if empty
- **`has_next`**: `True` if more pages exist beyond the current one
- **`has_prev`**: `True` if this page has items and is not the first page
- **`page`**: Current page number (1-indexed)
- **`page_size`**: Number of items per page (alias for `limit`; `None` when unlimited)
- **`total_pages`**: Total number of pages (0 when no results)

### Methods

- **`to_dict()`**: Returns the result as a dictionary with `offset`,
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
 'limit': 100,
 'total': 6,
 'page': 1,
 'page_size': 100,
 'total_pages': 1,
 'has_next': False,
 'has_prev': False,
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
--8<-- "guides/change-state/retrieve-aggregates/001.py:raw"
```

The query format is database-specific: a JSON string for the memory adapter,
SQL for SQLAlchemy, etc. All other query options (`order_by`, `offset`,
`limit`) are ignored for raw queries.

!!! warning
    Raw queries bypass Protean's query abstraction and are tied to a specific
    database technology. Use them sparingly and only when the QuerySet API
    cannot express your query.

## Query performance

A query that filters or sorts on the same fields repeatedly needs a database
index to stay fast as the table grows, without one, the database falls back to
a full scan. Declare the indexes a query path needs on the aggregate itself:

```python
--8<-- "guides/change-state/retrieve-aggregates/005.py:index"
```

This backs `filter(country="US").order_by("-age")` with a single index. See
[Declaring Indexes](../domain-definition/indexes.md) for the full workflow and
[Index Aggregates for Query Paths](../../patterns/index-aggregates-for-query-paths.md)
for choosing what to index.

---

!!! tip "See also"
    **Concept overview:** [Repositories](../../concepts/building-blocks/repositories.md): The role of repositories in DDD and how Protean implements the pattern.

    **Related guides:**

    - [Repositories](./repositories.md): Define custom repositories with domain-named query methods.
    - [Persist Aggregates](./persist-aggregates.md): Save and update aggregates through repositories.
    - [Declaring Indexes](../domain-definition/indexes.md): Index the fields your queries filter and sort on.
