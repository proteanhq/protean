# Type Checking

Protean ships a **mypy plugin** that teaches static type checkers about
the framework's runtime transformations, field factories that resolve to native
Python types and decorators that inject base classes. Without the plugin, mypy
reports false errors on perfectly correct Protean code.

The plugin handles two patterns:

1. **Field factories**: `String()`, `Integer()`, and peers return
   `FieldSpec` at the class level but resolve to `str`, `int`, etc. at
   runtime. The plugin maps each factory to its Python type.
2. **Decorator-based registration**: `@domain.aggregate`,
   `@domain.entity`, and the other element decorators make the class a
   subclass of its Protean base at runtime. The plugin adds the same base
   during type analysis, so methods like `raise_()` and `to_dict()`, the
   injected `id`, and a keyword `__init__` are visible to mypy, and the
   decorated class is accepted wherever a signature names its base class.

For the background on why this is needed, see
[Field System Internals](../../concepts/internals/field-system.md).

## Enabling the plugin

Add the plugin to `[tool.mypy]` in `pyproject.toml` (or an equivalent
`mypy.ini` / `setup.cfg`):

```toml
[tool.mypy]
plugins = ["protean.ext.mypy_plugin"]
```

Field type resolution and decorator base class injection are both enabled by
this single entry. There are no further flags.

Debug mode: set `PROTEAN_MYPY_DEBUG=1` to print plugin diagnostic
traces to stderr while mypy runs.

## Field Type Resolution

Field factories resolve to their Python types:

| Field | Resolved Type |
|-------|---------------|
| `String()` | <code>str &#124; None</code> |
| `String(required=True)` | `str` |
| `String(default="hello")` | `str` |
| `Integer()` | <code>int &#124; None</code> |
| `Float()` | <code>float &#124; None</code> |
| `Boolean()` | <code>bool &#124; None</code> |
| `Date()` | <code>datetime.date &#124; None</code> |
| `DateTime()` | <code>datetime.datetime &#124; None</code> |
| `List()` | `list` |
| `Dict()` | `dict` |
| `Identifier(identifier=True)` | `str` |
| `Auto(identifier=True)` | `str` |
| `ValueObject(Money)` | <code>Money &#124; None</code> |
| `ValueObject(Money, required=True)` | `Money` |
| `Reference(Order)` | <code>Order &#124; None</code> |
| `Reference(Order, required=True)` | `Order` |
| `HasOne(Shipment)` | <code>Shipment &#124; None</code> |
| `HasMany(LineItem)` | `list[LineItem]` |

Fields are `Optional` (union with `None`) unless they are `required=True`,
have a `default` other than `None`, or are `identifier=True`. Container fields (`List`, `Dict`)
always have an implicit default and are never `Optional`. A `default` does not
make `ValueObject` or `Reference` non-optional: a value object or reference
left out at construction reads as `None`. `HasOne` is always
`Optional`, because an association cannot be required at runtime. A target
named by string, such as `Reference("Order")`, resolves to `Any`, so the
annotation on the field states the type.

## Declaring fields for `mypy --strict`

The typed-annotation form gives every field its real type. The annotation
and the field call check each other, so a mismatch is a mypy error:

```python
from protean import Domain
from protean.fields import Float, HasMany, String, ValueObject

domain = Domain(name="Shop")


@domain.value_object
class Money:
    amount: float = Float(required=True)


@domain.entity(part_of="Order")
class LineItem:
    sku: str = String(required=True)


@domain.aggregate
class Order:
    customer: str = String(required=True, max_length=50)
    note: str | None = String()
    total: Money = ValueObject(Money, required=True)
    items: list[LineItem] = HasMany(LineItem)
```

Both of these lines are mypy errors:

```python
# fragment
count: int = String(required=True)  # error: str is not int
name: str = String()                # error: the field is optional
```

The assignment form (`customer = String(required=True)`) type-checks the
same way. See
[ADR-0038](../../adr/0038-canonical-field-style-for-mypy-strict.md)
for why the typed-annotation form is the canonical one.

The annotation-only form (`customer: String(required=True)`) also passes
`mypy --strict`, in a decorated element and in a class that inherits a
Protean base. mypy rejects a call in an annotation and keeps no type for it,
so the plugin replaces the annotation with `Any` and accepts the field as an
optional keyword argument. Construction by keyword and use of the field are
clean, but mypy does not check the field's type, and returning it from a
function declared to return `str` reports `no-any-return`. Move a field to
the typed-annotation form to get its real type.

mypy's note for a call with keyword arguments does not name the function, so
the plugin accepts any such call in an annotation as a field. A call without
keyword arguments counts only when it names a Protean field factory:
`label: str()` still reports `valid-type`.

## Decorator Base Class Injection

A class decorated with `@domain.aggregate` (or another element decorator)
is a subclass of the matching base class for mypy, as it is at runtime. For
aggregates, this exposes:

- `.id`: Auto-injected `str`
- `.raise_(event)`
- `.to_dict()`
- `.state_` and the other properties
- All other `BaseAggregate` methods and attributes

Because the class is a real subtype, it can be passed wherever the framework
asks for the base: `domain.cache_for(Leaderboard)`,
`cache.add(Leaderboard(...))`, `x: BaseValueObject = Money(...)`, and
`isinstance(aggregate, Auditable)` all type-check, and `super().__init__(...)`
in a decorated domain service reaches `BaseDomainService.__init__`.
Aggregates, entities, value objects, commands, events, projections and queries
also get a keyword `__init__` built from their Protean field declarations
and their plain annotations. A plain annotation such as `note: str` or
`note: str = ""` is a pydantic field at runtime, and it is accepted as a
keyword typed `Any`. A class that defines its own `__init__` keeps it, and so
does a decorated class that extends it, since that `__init__` is the one that
runs.

Supported decorators: `aggregate`, `entity`, `value_object`, `command`,
`event`, `domain_service`, `command_handler`, `event_handler`,
`application_service`, `subscriber`, `projection`, `projector`, `query`,
`query_handler`, `process_manager`, `repository`, `database_model`, `email`,
`upcaster`.

Both `@domain.aggregate` (bare) and `@domain.aggregate()` (called) forms
are detected. The decorator rebuilds the class on its Protean base alone, so
a mixin listed as a base is dropped at runtime, and the plugin drops it too.
A class that extends a decorated element, such as an aggregate extending a
decorated abstract aggregate, keeps its parent, and its `__init__` takes the
parent's fields. See
[ADR-0047](../../adr/0047-mypy-plugin-subclasses-decorated-elements.md)
for how the base is added.

## Typed framework entry points

- `domain.view_for(Projection)` returns `ReadView[Projection]`, so `.get()`
  and `.find_by()` return the projection class. Without the plugin, a
  decorated projection is not a `BaseProjection` subclass to a checker, and
  `view_for` returns `ReadView[Any]`. `.query` returns a
  `ReadOnlyQuerySet`, and its results are not typed by projection.
- `QuerySet` chain methods (`filter`, `exclude`, `order_by`, `limit`,
  `offset`, `only`) return the queryset's own type, so a `ReadOnlyQuerySet`
  stays read-only through a chain.
- `cls._create_new()` and `cls.from_events(...)` on an event-sourced
  aggregate return that aggregate's class.
- `@handle` takes an event or command class, an event type string such as
  `"Customers.CustomerFact.v1"`, or the `"$any"` wildcard, and the decorated
  method keeps its signature. The framework calls a handler positionally
  with the message, and a redelivery that consume-side idempotency skips
  returns `None`.
- `@domain.upcaster(event_type=..., from_version=..., to_version=...)` keeps
  the decorated class's type.

## VS Code

When running mypy through the VS Code **Mypy Type Checker** extension
(`ms-python.mypy-type-checker`), Pylance's strict checker has to be
disabled because it cannot read the plugin. The settings combination:

```json
{
    "python.analysis.typeCheckingMode": "off",
    "mypy-type-checker.args": ["--config-file=pyproject.toml"],
    "mypy-type-checker.importStrategy": "fromEnvironment"
}
```

Protean's own repository ships this configuration in its
`.vscode/settings.json` for reference.

## Known Limitations

- **`auto_add_id_field=False`**: The plugin does not inspect decorator
  arguments. If you pass `auto_add_id_field=False` to `@domain.aggregate`,
  the plugin still injects `id`. Use `# type: ignore[attr-defined]` if needed.

- **Autocomplete for injected methods**: The base class is added for mypy
  only. IDE engines that do not run the plugin, such as Pylance, may not
  show the base's methods in suggestions.

- **Explicit inheritance**: If you already inherit from a base class
  (e.g. `class Order(BaseAggregate):`), the plugin detects this and skips
  injection to avoid duplicates.
