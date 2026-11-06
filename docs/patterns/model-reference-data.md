# Model Reference Data as Domain Concepts

## The Problem

Every application accumulates **reference data**: the slowly-changing,
enumerable values that other records point at: currencies, countries, order
statuses, product categories, tax codes, units of measure. Developers used to
database-first design often store all of it in one shared table:

```python
# fragment
@domain.aggregate
class MasterData:
    master_id: Auto(identifier=True)
    category: String(required=True)      # "CURRENCY", "ORDER_STATUS", "COUNTRY"
    code: String(required=True)          # "USD", "SHIPPED", "IN"
    label: String(required=True)         # "US Dollar", "Shipped", "India"
    sort_order: Integer(default=0)
    active: Boolean(default=True)
    extra: Dict()                        # a grab-bag for the fields that don't fit
```

One table, every lookup. It feels economical. Then it causes these problems as
the application grows:

- **You lose type safety**: A `Currency` row and an `OrderStatus` row are the
  same Python type. Nothing stops a handler from assigning a country code where
  a currency was expected. The compiler can't catch the mistake. Only code that
  inspects the data at runtime can tell them apart.

- **Invariants degrade into deferred lookups**: "An order's status must be one
  of the valid statuses" can no longer be a domain rule. It becomes a query
  against `MasterData WHERE category='ORDER_STATUS'` that runs at runtime. The
  aggregate that depends on the rule no longer contains it.

- **Every consumer reinvents the lookup**: There is no `Currency` concept to
  import. So every module that needs currencies writes its own
  `filter(category="CURRENCY")`, its own caching, its own "is this code valid?"
  check. Developers copy this logic between modules, and the copies stop
  matching over time.

- **The schema becomes a lowest common denominator**: A currency needs a
  `symbol`. A country needs an ISO-3 code and a dialing prefix. A tax code needs
  a rate. None of these fit the shared columns, so they all get stuffed into the
  `extra` grab-bag, where they sit untyped, unvalidated, and unsearchable.

- **The surrogate key leaks everywhere**: Because the table has its own
  `master_id`, foreign keys point at that opaque integer instead of the natural
  `code`. When you read raw data, you now need a join to find out that row
  `4471` means `"USD"`.

This is the **One True Lookup Table** anti-pattern (also called MUCK, the
*Massively Unified Code-Key* table). It stores a dozen unrelated domain
concepts in a single storage shape. In doing so, it makes a persistence
convenience part of the domain model.

The root cause: **a single physical table has been mistaken for a single domain
concept.**

---

## The Pattern

Model each *kind* of reference data as its own domain type, with its own
table.

```
One True Lookup Table:
  MasterData(category, code, label, ...)   # Currency, Country, Status... all one type

Domain concepts:
  Currency      # its own type, its own fields, its own rules
  Country       # its own type
  OrderStatus   # its own type
```

The right Protean construct depends on a single axis: **does the set change at
runtime?**

```
Closed & static (known at design time)        Open & dynamic (admin-managed)
  order statuses, units of measure              currencies, countries, tax codes
  ────────────────────────────────             ──────────────────────────────────
  Enumeration value object                      Aggregate keyed by `code`
  or String(choices=[...])                      + repository + (optional) cache
  No persistence                                Persisted, queryable, evolvable
```

- **When the set is closed and static**: The values are part of the model's
  vocabulary and rarely change. Encode them in the type system: a
  `String(choices=[...])` constraint for a bare code, or an **enumeration value
  object** when the value carries a label or behavior.

- **When the set is open and dynamic**: Operators add and retire values at
  runtime. Model each such kind of reference data as its own **aggregate**,
  with the natural `code` as its identity. A repository loads the aggregate. A
  cache-backed projection or a catalog service makes it available across the
  application.

Either way, the concept has its own name and its own type, defined in one
place. Consumers import `Currency`, not `MasterData WHERE category='CURRENCY'`.

---

## How Protean Supports This

### Field-level choices for closed codes

When a value is just a constrained string, `choices` makes invalid values
unrepresentable at the field level, with no extra type:

```python
--8<-- "patterns/model-reference-data/001.py:choices"
```

### Enumeration value objects for richer closed sets

When a closed value needs a label, a symbol, or behavior, model it as a value
object with a frozen registry. It is immutable, equality-by-value, and carries
no identity, exactly what reference data is.

### Aggregates keyed by a natural code

A Protean aggregate takes a single surrogate identity. That identity can be the
natural `code` itself, via `String(identifier=True)`. Editable reference data
becomes an ordinary aggregate with an ordinary repository, with no special
machinery.

### Custom repositories for "all of a kind"

A `@domain.repository` method expresses the "give me the whole set" and "give me
the `code → value` map" queries once, in one place, instead of scattering
`filter(...)` calls across consumers.

### Cache-backed projections for app-wide reads

Reference data is read constantly and written rarely, which makes it an ideal
projection. A cache-backed projection (`@domain.projection(cache="redis")`)
keeps lookups off the write model and out of the hot path, refreshed by a
projector when the underlying aggregate changes.

---

## Applying the Pattern

### Closed set: enumeration value object

Order statuses are known at design time. They never get added by an operator.
Model them as a value object with a registry, so the type system defines the
set and aggregate invariants can check it:

**Before: a row in the lookup table**

```python
# fragment
# status is a foreign key into MasterData WHERE category='ORDER_STATUS'
order.status_id = 4471   # what does 4471 mean? a join will tell you.
```

**After: an enumeration value object**

```python
--8<-- "patterns/model-reference-data/002.py:value_object"
```

Now the status is a typed concept, and the registry is the single source of
truth. An aggregate holds the status as a field:

```python
--8<-- "patterns/model-reference-data/002.py:aggregate"
```

Protean now checks an order status when it constructs the value object, as part
of the *always-valid* guarantee. The database no longer has to catch an invalid
status later through a foreign-key check.

### Editable reference: aggregate keyed by code

Currencies are administered at runtime: a back-office user adds a new one,
deactivates an obsolete one, or fixes a symbol. That lifecycle makes it an
aggregate. The natural `code` is its identity:

```python
--8<-- "patterns/model-reference-data/003.py:aggregate"
```

Each kind of reference data is its own aggregate, with its own table
(`currency`, `country`, `tax_code`), its own fields, and its own rules. That is
the DDD-correct outcome: distinct concepts, distinctly stored. You seed the set
and load one entry with ordinary repository calls:

```python
--8<-- "patterns/model-reference-data/003.py:load_one"
```

### A list of a kind: the `code → value` map

The recurring need is rarely a single entry; it is "give me all active
currencies" or "give me the `code → Currency` map for a dropdown." Express it
once on a custom repository, not as a `filter(...)` copied into every consumer:

```python
--8<-- "patterns/model-reference-data/003.py:repository"
```

Consumers get a typed list or a typed map, never raw rows:

```python
--8<-- "patterns/model-reference-data/003.py:consumer"
```

### App-wide read access: a cache-backed catalog projection

Reference data is read on nearly every request and written a handful of times a
month. If the application loads it from the write aggregate on every call, it
does needless work. Project it into a cache-backed read model, refreshed by a
projector when the aggregate changes:

```python
# fragment
@domain.projection(cache="redis")
class CurrencyOption:
    code: String(identifier=True)
    name: String(required=True)
    symbol: String(max_length=4)


@domain.projector(projector_for=CurrencyOption, aggregates=[Currency])
class CurrencyCatalogProjector:
    @on(CurrencyAdded)
    def add_option(self, event: CurrencyAdded) -> None:
        cache = current_domain.cache_for(CurrencyOption)
        cache.add(CurrencyOption(code=event.code, name=event.name,
                                 symbol=event.symbol))

    @on(CurrencyDeactivated)
    def remove_option(self, event: CurrencyDeactivated) -> None:
        cache = current_domain.cache_for(CurrencyOption)
        cache.remove_by_key(f"currency_option:::{event.code}")
```

A cache-backed projection has no repository, so the projector writes through
`cache_for()` and readers use `view_for()`. Cache keys have the form
`<prefix>:::<identifier>`, where the prefix is the projection's class name in
snake case (`CurrencyOption` becomes `currency_option`). If you rename the
class, the key that the projector must remove changes too.

The read side is now a fast, cache-resident `code → option` catalog, decoupled
from the write model, with a single invalidation point (the projector). When
consumers must also query the catalog by attributes or join it into reports,
back the same projection with a database provider instead of a cache. The rest
of the pattern stays the same.

---

## A single physical table is not supported

Sometimes a legacy `master_data` table is an immovable infrastructure
constraint: a shared database that other systems already read. Protean cannot
map several aggregates onto that one table. Each aggregate gets its own table.
Two database models cannot share a `schema_name`. With a SQL provider, the
second model on the same `schema_name` fails at startup with SQLAlchemy's
`InvalidRequestError: Table 'master_data' is already defined`.

Keep `Currency` and `Country` as separate aggregates with separate tables.
Other systems may still need to read `master_data`. In that case, update that
table outside the domain model so it matches the aggregate tables.

---

## Anti-Patterns

### Modeling the lookup table in the domain

```python
# fragment
# Anti-pattern: the storage shape becomes a domain concept
@domain.aggregate
class MasterData:
    master_id: Auto(identifier=True)
    category: String()
    code: String()
    label: String()
```

This is the One True Lookup Table, declared as an aggregate with
`@domain.aggregate`. `MasterData` is not a concept anyone in the business talks
about; `Currency` and `Country` are. Model the concepts, not the table.

### The discriminator as a domain field

```python
# fragment
# Anti-pattern: leaking the storage discriminator into the model
@domain.aggregate
class Currency:
    code: String(identifier=True)
    category: String(default="CURRENCY")   # why does a Currency know this?
```

A `Currency` is always a currency. A `category` field exists only to
distinguish rows in a shared table. That field brings a persistence concern
into the domain.

### Scattering raw lookups through domain logic

```python
# fragment
# Anti-pattern: every consumer re-implements the lookup
valid = current_domain.repository_for(MasterData).query.filter(
    category="CURRENCY", active=True
).all().items
if any(c.code == command.currency for c in valid):
    ...
```

This duplicates the query, the caching, and the "is it valid?" logic in every
module that touches currencies. Centralize it behind a named type and a
repository method (`CurrencyRepository.as_map()`), written once.

### Foreign keys to the surrogate id

```python
# fragment
# Anti-pattern: pointing at the opaque lookup-table id
order.currency_id = 4471          # what currency is 4471? nobody knows without a join
```

Reference data has a perfectly good natural key, the `code`. Use the `code` as
the aggregate's identity. Then store `currency_code = "USD"`. The data is
readable on its own. A missing currency is then obvious instead of a dangling
integer.

---

## When Not to Use / Trade-offs

- **Trivial flags don't need a type**: A bare `String(choices=[...])` serves a
  two- or three-value set with no label and no behavior (`"draft" | "active" |
  "archived"`) well. If you promote it to a value object, you add code and gain
  nothing.

- **Static vs. dynamic is a judgement call that can change**: Some sets start
  closed (shipping carriers, say) and later need runtime administration. You
  can start with an enumeration value object and migrate to an aggregate later
  as a deliberate refactor. Model for what you know now, and leave a
  hypothetical future out of the model.

- **The cache is a freshness trade-off**: A cache-backed catalog is fast but
  eventually consistent: a newly added currency appears once the projector runs.
  For data that must be immediately consistent on the write path, validate
  against the aggregate repository, not the cached projection.

---

## Summary

| Data character | Construct | Persistence | Validity enforced |
|----------------|-----------|-------------|-------------------|
| Bare closed code | `String(choices=[...])` | None | Field constraint |
| Closed code + label/behavior | Enumeration value object | None | VO invariant, at construction |
| Editable, queryable | Aggregate keyed by `code` | Own table | Aggregate invariant |
| Read everywhere, written rarely | Cache-backed projection | Cache/provider | Refreshed by projector |

One physical table is not one domain concept. Model each kind of reference data
as its own type. Use an enumeration value object for a closed, static kind, and
an aggregate keyed by its natural code for an editable kind.

---

!!! tip "Related reading"
    **Patterns:**

    - [Replace Primitives with Value Objects](replace-primitives-with-value-objects.md): Extracting validated, composite values into value objects.
    - [Design Projection Granularity Around Consumer Needs](projection-granularity.md): Shaping read models, including cache-backed projections for volatile data.
    - [Validation Layering](validation-layering.md): Where reference-data validity belongs across the four validation layers.

    **Concepts:**

    - [Value Objects](../concepts/building-blocks/value-objects.md): Immutable descriptive objects without identity.
    - [Projections](../concepts/building-blocks/projections.md): Read-optimized views and their storage options.

    **Guides:**

    - [Database Models](../guides/change-state/database-models.md): Custom `@domain.database_model` mappings and `schema_name`.
    - [Repositories](../guides/change-state/repositories.md): Custom repository methods for retrieving collections.
