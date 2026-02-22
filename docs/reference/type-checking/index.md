# Type Checking

Protean ships with a **mypy plugin** that makes static type checkers understand
the framework's runtime transformations. Without the plugin, tools like mypy
report false errors because they cannot see the base classes and field types
that Protean injects dynamically.

## Why a Plugin is Needed

Protean uses two patterns that are invisible to static analysis:

1. **Field factories** — `String()`, `Integer()`, etc. return `FieldSpec`
   objects at the class level, but at runtime the descriptor protocol resolves
   them to `str`, `int`, and so on. The plugin teaches mypy the correct return
   types.

2. **Decorator-based registration** — `@domain.aggregate`, `@domain.entity`,
   and other decorators call `derive_element_class()` at runtime, which
   dynamically injects a base class (e.g. `BaseAggregate`) via
   `type(name, (base_cls,), ...)`. The plugin injects these base classes
   during type analysis so that methods like `raise_()`, `to_dict()`, and
   auto-injected attributes like `id` are visible.

## Quick Setup

Add the plugin to your mypy configuration in `pyproject.toml`:

```toml
[tool.mypy]
plugins = ["protean.ext.mypy_plugin"]
```

That's it. Both field type resolution and decorator base class injection are
enabled automatically.

## What the Plugin Does

### Field Type Resolution

Field factories resolve to their Python types:

| Field | Resolved Type |
|-------|---------------|
| `String()` | `str \| None` |
| `String(required=True)` | `str` |
| `String(default="hello")` | `str` |
| `Integer()` | `int \| None` |
| `Float()` | `float \| None` |
| `Boolean()` | `bool \| None` |
| `Date()` | `datetime.date \| None` |
| `DateTime()` | `datetime.datetime \| None` |
| `List()` | `list` |
| `Dict()` | `dict` |
| `Identifier(identifier=True)` | `str` |
| `Auto(identifier=True)` | `str` |

Fields are `Optional` (union with `None`) unless they are `required=True`,
have a `default`, or are `identifier=True`. Container fields (`List`, `Dict`)
always have an implicit default and are never `Optional`.

### Decorator Base Class Injection

When you write:

```python
@domain.aggregate
class Customer:
    name = String(required=True)
```

The plugin makes mypy see `Customer` as if it inherits from `BaseAggregate`,
giving access to:

- `customer.id` — auto-injected `str` for aggregates and entities
- `customer.raise_(event)` — raise domain events
- `customer.to_dict()` — serialize to dictionary
- `customer._events` — event list
- All other `BaseAggregate` methods and attributes

This works for all 15 decorator types: `aggregate`, `entity`, `value_object`,
`command`, `event`, `domain_service`, `command_handler`, `event_handler`,
`application_service`, `subscriber`, `projection`, `projector`, `repository`,
`database_model`, and `email`.

Both `@domain.aggregate` (without parens) and `@domain.aggregate()` (with
parens) are supported.

## VS Code Setup

For the best experience in VS Code:

1. Install the **mypy** extension (`ms-python.mypy-type-checker`)
2. Disable Pylance's type checking (keep Pylance for autocomplete and
   go-to-definition):

```json
{
    "python.analysis.typeCheckingMode": "off",
    "mypy-type-checker.args": ["--config-file=pyproject.toml"],
    "mypy-type-checker.importStrategy": "fromEnvironment"
}
```

The project's `.vscode/settings.json` and `.vscode/extensions.json` already
include these settings and extension recommendations.

## Known Limitations

- **`auto_add_id_field=False`** — The plugin does not inspect decorator
  arguments. If you pass `auto_add_id_field=False` to `@domain.aggregate`,
  the plugin still injects `id`. Use `# type: ignore[attr-defined]` if needed.

- **Autocomplete for injected methods** — While mypy correctly type-checks
  injected base class methods, some IDE autocomplete engines may not show them
  in suggestions because the base class is not in the explicit MRO.

- **Explicit inheritance** — If you already inherit from a base class
  (e.g. `class Order(BaseAggregate):`), the plugin detects this and skips
  injection to avoid duplicates.
