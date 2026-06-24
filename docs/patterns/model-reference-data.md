# Model Reference Data as Domain Concepts

## The Problem

Every application accumulates **reference data**: the slowly-changing,
enumerable values that other records point at: currencies, countries, order
statuses, product categories, tax codes, units of measure. A common instinct,
inherited from database-first thinking, is to store all of it in one shared
table:

```python
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

One table, every lookup. It feels economical. Then it rots:

- **Type safety evaporates.** A `Currency` row and an `OrderStatus` row are the
  same Python type. Nothing stops a handler from assigning a country code where
  a currency was expected. The compiler can't help; only runtime data can tell
  them apart.

- **Invariants degrade into deferred lookups.** "An order's status must be one
  of the valid statuses" can no longer be a domain rule. It becomes a query
  against `MasterData WHERE category='ORDER_STATUS'`, executed at runtime, far
  from the aggregate that depends on it.

- **Every consumer reinvents the lookup.** There is no `Currency` concept to
  import. So every module that needs currencies writes its own
  `filter(category="CURRENCY")`, its own caching, its own "is this code valid?"
  check. The logic is copy-pasted and drifts.

- **The schema becomes a lowest common denominator.** A currency needs a
  `symbol`. A country needs an ISO-3 code and a dialing prefix. A tax code needs
  a rate. None of these fit the shared columns, so they all get stuffed into the
  `extra` grab-bag, where they sit untyped, unvalidated, and unsearchable.

- **The surrogate key leaks everywhere.** Because the table has its own
  `master_id`, foreign keys point at that opaque integer instead of the natural
  `code`. Now reading raw data requires a join just to discover that row `4471`
  means `"USD"`.

This is the **One True Lookup Table** anti-pattern (also called MUCK, the
*Massively Unified Code-Key* table). It collapses a dozen unrelated domain
concepts into a single storage shape and, in doing so, imports a persistence
convenience straight into the heart of the domain model.

The root cause: **a single physical table has been mistaken for a single domain
concept.**

---

## The Pattern

Model each *kind* of reference data as its own first-class domain type. A
shared physical table, if you truly need one, is an adapter detail, decided
last, expressed in the model layer, invisible to the domain.

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

- **Closed and static.** The values are part of the model's vocabulary and
  rarely change. Encode them in the type system: a `String(choices=[...])`
  constraint for a bare code, or an **enumeration value object** when the value
  carries a label or behavior.

- **Open and dynamic.** Operators add and retire values at runtime. The kind
  earns its own **aggregate**, with the natural `code` as its identity. A
  repository loads it; a cache-backed projection or a catalog service makes it
  available across the application.

Either way, the concept has a name, a type, and a home. Consumers import
`Currency`, not `MasterData WHERE category='CURRENCY'`.

---

## How Protean Supports This

### Field-level choices for closed codes

When a value is just a constrained string, `choices` makes invalid values
unrepresentable at the field level, with no extra type:

```python
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    status: String(choices=["draft", "placed", "shipped", "delivered"],
                   default="draft")
```

### Enumeration value objects for richer closed sets

When a closed value needs a label, a symbol, or behavior, model it as a value
object with a frozen registry. It is immutable, equality-by-value, and carries
no identity, exactly what reference data is.

### Aggregates keyed by a natural code

Protean aggregates take a single surrogate identity, and that identity can be
the natural `code` itself via `String(identifier=True)`. Editable reference
data becomes an ordinary aggregate with an ordinary repository, with no special
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
Model them as a value object with a registry, so the set lives in the type
system and participates in aggregate invariants:

**Before: a row in the lookup table**

```python
# status is a foreign key into MasterData WHERE category='ORDER_STATUS'
order.status_id = 4471   # what does 4471 mean? a join will tell you.
```

**After: an enumeration value object**

```python
@domain.value_object
class OrderStatus:
    code: String(required=True)
    label: String(required=True)

    @invariant.post
    def code_must_be_known(self):
        if self.code not in _ORDER_STATUSES:
            raise ValidationError(
                {"code": [f"Unknown order status: {self.code}"]}
            )

    @classmethod
    def of(cls, code: str) -> "OrderStatus":
        return cls(code=code, label=_ORDER_STATUSES[code])

    @classmethod
    def all(cls) -> list["OrderStatus"]:
        return [cls(code=c, label=l) for c, l in _ORDER_STATUSES.items()]


_ORDER_STATUSES = {
    "draft": "Draft",
    "placed": "Placed",
    "shipped": "Shipped",
    "delivered": "Delivered",
}
```

Now the status is a typed concept, the registry is the single source of truth,
and an aggregate invariant can reference it directly:

```python
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    status = ValueObject(OrderStatus)

# Valid
order = Order(status=OrderStatus.of("placed"))

# Invalid: raises ValidationError at construction, no database round-trip
order = Order(status=OrderStatus(code="teleported", label="?"))
```

The validity of an order status is now part of the *always-valid* guarantee,
caught at construction, instead of a foreign-key check deferred to the database.

### Editable reference: aggregate keyed by code

Currencies are administered at runtime: a back-office user adds a new one,
deactivates an obsolete one, or fixes a symbol. That lifecycle makes it an
aggregate. The natural `code` is its identity:

```python
@domain.aggregate
class Currency:
    code: String(identifier=True, max_length=3)   # "USD" is the identity
    name: String(required=True)
    symbol: String(max_length=4)
    minor_units: Integer(default=2)                # 2 for USD, 0 for JPY
    is_active: Boolean(default=True)

    @invariant.post
    def code_must_be_iso_4217(self):
        if len(self.code) != 3 or not self.code.isalpha():
            raise ValidationError(
                {"code": ["Currency code must be a 3-letter ISO 4217 code"]}
            )

    def deactivate(self) -> None:
        self.is_active = False
        self.raise_(CurrencyDeactivated(code=self.code))
```

Each kind of reference data is its own aggregate, with its own table
(`currency`, `country`, `tax_code`), its own fields, and its own rules. That is
the DDD-correct outcome: distinct concepts, distinctly stored. Loading one is an
ordinary repository call:

```python
repo = current_domain.repository_for(Currency)
usd = repo.get("USD")            # the code IS the identity
```

### A list of a kind: the `code → value` map

The recurring need is rarely a single entry; it is "give me all active
currencies" or "give me the `code → Currency` map for a dropdown." Express it
once on a custom repository, not as a `filter(...)` copied into every consumer:

```python
@domain.repository(part_of=Currency)
class CurrencyRepository:
    def all_active(self) -> list[Currency]:
        return self.query.filter(is_active=True).all().items

    def as_map(self) -> dict[str, Currency]:
        """code → Currency, ready for validation or a dropdown."""
        return {c.code: c for c in self.all_active()}
```

Consumers get a typed list or a typed map, never raw rows:

```python
repo = current_domain.repository_for(Currency)

currencies = repo.all_active()           # list[Currency]
by_code = repo.as_map()                  # {"USD": Currency(...), "EUR": ...}

if command.currency not in by_code:
    raise ValidationError({"currency": ["Unknown currency"]})
```

### App-wide read access: a cache-backed catalog projection

Reference data is read on nearly every request and written a handful of times a
month. Reading it from the write aggregate on every call is wasteful. Project it
into a cache-backed read model, refreshed by a projector when the aggregate
changes:

```python
@domain.projection(cache="redis")
class CurrencyOption:
    code: String(identifier=True)
    name: String(required=True)
    symbol: String(max_length=4)


@domain.projector(projector_for=CurrencyOption, aggregates=[Currency])
class CurrencyCatalogProjector:
    @on(CurrencyAdded)
    def add_option(self, event: CurrencyAdded) -> None:
        repo = current_domain.repository_for(CurrencyOption)
        repo.add(CurrencyOption(code=event.code, name=event.name,
                                symbol=event.symbol))

    @on(CurrencyDeactivated)
    def remove_option(self, event: CurrencyDeactivated) -> None:
        repo = current_domain.repository_for(CurrencyOption)
        repo.remove(repo.get(event.code))
```

The read side is now a fast, cache-resident `code → option` catalog, decoupled
from the write model, with a single invalidation point (the projector). When the
catalog must also be queried by attributes or joined into reports, back the same
projection with a database provider instead of a cache; the shape of the
pattern is unchanged.

---

## The single physical table as an adapter escape hatch

Sometimes a legacy `master_data` table is an immovable infrastructure
constraint: a shared database that other systems already read. That constraint
belongs in the **model layer**, never the domain. Keep the domain concepts
distinct and point their custom models at the same `schema_name`:

```python
@domain.aggregate
class Currency:
    code: String(identifier=True, max_length=3)
    name: String(required=True)
    symbol: String(max_length=4)


@domain.model(part_of=Currency)
class CurrencyModel:
    class Meta:
        schema_name = "master_data"      # the shared physical table


@domain.aggregate
class Country:
    code: String(identifier=True, max_length=2)
    name: String(required=True)


@domain.model(part_of=Country)
class CountryModel:
    class Meta:
        schema_name = "master_data"      # same table, different concept
```

The domain still sees `Currency` and `Country` as separate, fully-typed
concepts; only the adapter knows they share a table. Treat this as a true escape
hatch: a `category` discriminator column and per-concept scoping must be managed
in the custom models and repositories yourself, and Protean will not synthesize
that filtering for you. Reach for it only when a separate table per concept is
genuinely not an option.

---

## Anti-Patterns

### Modeling the lookup table in the domain

```python
# Anti-pattern: the storage shape becomes a domain concept
@domain.aggregate
class MasterData:
    master_id: Auto(identifier=True)
    category: String()
    code: String()
    label: String()
```

This is the One True Lookup Table wearing a decorator. `MasterData` is not a
concept anyone in the business talks about; `Currency` and `Country` are. Model
the concepts, not the table.

### The discriminator as a domain field

```python
# Anti-pattern: leaking the storage discriminator into the model
@domain.aggregate
class Currency:
    code: String(identifier=True)
    category: String(default="CURRENCY")   # why does a Currency know this?
```

A `Currency` is always a currency. A `category` field that exists only to
distinguish rows in a shared table is a persistence concern that has leaked into
the domain. If a shared table is unavoidable, the discriminator lives in the
custom model, not the aggregate.

### Scattering raw lookups through domain logic

```python
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
# Anti-pattern: pointing at the opaque lookup-table id
order.currency_id = 4471          # what currency is 4471? nobody knows without a join
```

Reference data has a perfectly good natural key, the `code`. Use it as the
aggregate's identity and store `currency_code = "USD"`. The data is readable on
its own, and a missing currency is obvious instead of a dangling integer.

---

## When Not to Use / Trade-offs

- **Trivial flags don't need a type.** A two- or three-value set with no label
  and no behavior (`"draft" | "active" | "archived"`) is well served by a bare
  `String(choices=[...])`. Promoting it to a value object adds ceremony without
  benefit.

- **Static vs. dynamic is a judgement call that can change.** A set that starts
  closed (shipping carriers, say) may later need runtime administration. Starting
  with an enumeration value object and migrating to an aggregate is a deliberate
  refactor; model for what you know now, not a hypothetical future.

- **The cache is a freshness trade-off.** A cache-backed catalog is fast but
  eventually consistent: a newly added currency appears once the projector runs.
  For data that must be immediately consistent on the write path, validate
  against the aggregate repository, not the cached projection.

- **The shared-table escape hatch carries ongoing cost.** Discriminator scoping,
  migrations, and query filtering become your responsibility. Accept it only
  when a table-per-concept is truly off the table.

---

## Summary

| Data character | Construct | Persistence | Validity enforced |
|----------------|-----------|-------------|-------------------|
| Bare closed code | `String(choices=[...])` | None | Field constraint |
| Closed code + label/behavior | Enumeration value object | None | VO invariant, at construction |
| Editable, queryable | Aggregate keyed by `code` | Own table | Aggregate invariant |
| Read everywhere, written rarely | Cache-backed projection | Cache/provider | Refreshed by projector |
| Legacy shared table required | Aggregates + custom models on one `schema_name` | Shared table (adapter) | Aggregate invariant |

The principle: **one physical table is not one domain concept. Model each kind
of reference data as its own type: an enumeration value object when it is
closed and static, or an aggregate keyed by its natural code when it is editable.
Treat any shared storage table as an adapter detail, never a domain model.**

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

    - [Database Models](../guides/change-state/database-models.md): Custom `@domain.model` mappings and `schema_name`.
    - [Repositories](../guides/change-state/repositories.md): Custom repository methods for retrieving collections.
