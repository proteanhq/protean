# Retreiving Aggregates

An aggregate can be retreived with the repository's `get` method, if you know
its identity:

```python hl_lines="16 20"
{! docs_src/guides/change_state_001.py !}
```

1.  Identity is explicitly set to **1**.

```shell hl_lines="1"
In [1]: domain.repository_for(Person).get("1")
Out[1]: <Person: Person object (id: 1)>
```

Finding an aggregate by a field value is also possible, but requires a custom
repository to be defined with a business-oriented method.

## Custom Repositories

Protean needs anything beyond a simple `get` to be defined in a
repository. A repository is to be treated as part of the domain layer, and is
expected to enclose methods that represent business queries.

Defining a custom repository is straight-forward:

```python hl_lines="16"
{! docs_src/guides/change_state_004.py !}
```

1. The repository is connected to `Person` aggregate through the `part_of`
parameter.

Protean now returns `CustomPersonRepository` upon fetching the repository for
`Person` aggregate.

```shell hl_lines="11 14"
In [1]: person1 = Person(name="John Doe", email="john.doe@example.com", age=22)

In [2]: person2 = Person(name="Jane Doe", email="jane.doe@example.com", age=20)

In [3]: repository = domain.repository_for(Person)

In [4]: repository
Out[4]: <CustomPersonRepository at 0x1079af290>

In [5]: repository.add(person1)
Out[5]: <Person: Person object (id: 9ba6a890-e783-455e-9a6b-a0a16c0514df)>

In [6]: repository.add(person2)
Out[6]: <Person: Person object (id: edc78a03-aba6-47fc-a4a7-308eed3f7c67)>

In [7]: retreived_person = repository.find_by_email("john.doe@example.com")

In [8]: retreived_person.to_dict()
Out[8]: 
{'name': 'John Doe',
 'email': 'john.doe@example.com',
 'age': 22,
 'id': '9ba6a890-e783-455e-9a6b-a0a16c0514df'}
```

!!!note
    Methods in the repository should be named for the business queries they
    perform. `adults` is a good name for a method that fetches persons
    over the age of 18.

!!!note
   A repository can be connected to a specific persistence store by specifying
   the `database` parameter.

## Data Acsess Objects (DAO)

You would have observed the query in the repository above was performed on a
`_dao` object. This is a DAO object that is automatically generated for every
repository, and internally used by Protean to access the persistence layer.

At first glance, repositories and Data Access Objects may seem similar.
But a repository leans towards the domain in its functionality. It contains
methods and implementations that clearly identify what the domain is trying to
ask/do with the persistence store. Data Access Objects, on the other hand,
talk the language of the database. A repository works in conjunction with the
DAO layer to access and manipulate on the persistence store.

## Filtering

For all other filtering needs, the DAO exposes a method `filter` that can
accept advanced filtering criteria.

For the purposes of this guide, assume that the following `Person` aggregates
exist in the database:

```python hl_lines="7-11"
{! docs_src/guides/change_state_005.py !}
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

Queries below can be placed in repository methods.

### Finding by multiple fields

Used when you want to find a single aggregate. Throws `ObjectNotFoundError` if
no aggregates are found, and `TooManyObjectsError` when more than one
aggregates are found.

```shell
In [1]: person = repository._dao.find_by(age=36, country="CA")

In [2]: person.name
Out[2]: 'Jane Doe'
```

### Filtering by multiple fields

You can filter for more than one aggregate at a time, with a similar mechanism:

```shell
In [1]: people = repository._dao.query.filter(age__gte=18, country="CA").all().items

In [2]: [person.name for person in people]
Out[2]: ['John Doe', 'Jane Doe']
```

### Advanced filtering criteria

You would have observed that the query above contained a special annotation,
`_gte`, to signify that the age should be greater than or equal to 18. There
are many other annotations that can be used to filter results:

- **`exact`:** Match exact string
- **`iexact`:** Match exact string, case-insensitive
- **`contains`:** Match strings containing value
- **`icontains`:** Match strings containing value, case-insensitive
- **`gt`:** Match integer vales greater than value
- **`gte`:** Match integer vales greater than or equal to value
- **`lt`:** Match integer vales less than value
- **`lte`:** Match integer vales less than or equal to value
- **`in`:** Match value to be among list of values
- **`any`:** Match any of given values to be among list of values

These annotations have database-specific implementations. Refer to your chosen
adapter's documentation for supported advanced filtering criteria.

## Sorting results

The `filter` method supports a param named `order_by` to specify the sort order
of the results.

```shell
In [1]: people = repository._dao.query.order_by("-age").all().items

In [2]: [(person.name, person.age) for person in people]
Out[2]: 
[('John Roe', 41),
 ('John Doe', 38),
 ('Jane Doe', 36),
 ('Girl Doe', 11),
 ('Boy Doe', 8),
 ('Baby Doe', 3)]
```

The `-` in the column name reversed the sort direction in the above example.

## Resultset

The `filter(...).all()` method returns a `RecordSet` instance.

This class prevents DAO-specific data structures from leaking into the domain
layer. It exposes basic aspects of the returned results for inspection and
later use:

- **`total`:** Total number of aggregates matching the query
- **`items`:** List of query results
- **`limit`:** Number of aggregates to be fetched
- **`offset`:** Number of aggregates to skip

```shell
In [1]: result = repository._dao.query.all()

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
