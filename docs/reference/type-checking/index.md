# Type Checking

Protean ships a **mypy plugin** that teaches static type checkers about
the framework's runtime transformations — field factories that resolve
to native Python types and decorators that inject base classes. Without
the plugin, mypy reports false errors on perfectly correct Protean code.

The plugin handles two patterns:

1. **Field factories** — `String()`, `Integer()`, and peers return
   `FieldSpec` at the class level but resolve to `str`, `int`, etc. at
   runtime. The plugin maps each factory to its Python type.
2. **Decorator-based registration** — `@domain.aggregate`,
   `@domain.entity`, and the other element decorators dynamically inject
   base classes at runtime. The plugin injects the same base classes
   during type analysis so methods like `raise_()`, `to_dict()`, and
   injected attributes like `id` are visible to mypy.

For the background on why this is needed, see
[Field System Internals](../../concepts/internals/field-system.md).

## Enabling the plugin

Add the plugin to `[tool.mypy]` in `pyproject.toml` (or an equivalent
`mypy.ini` / `setup.cfg`):

```toml
[tool.mypy]
plugins = ["protean.ext.mypy_plugin"]
```

Field type resolution and decorator base class injection are both
enabled by this single entry — there are no further flags.

Debug mode: set `PROTEAN_MYPY_DEBUG=1` to print plugin diagnostic
traces to stderr while mypy runs.

## Field Type Resolution

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

## Decorator Base Class Injection

After `@domain.aggregate`-decorated (or equivalently decorated) classes are
analyzed, mypy sees them as if they inherit from the corresponding base
class. For aggregates, this exposes:

- `.id` — auto-injected `str`
- `.raise_(event)`
- `.to_dict()`
- `._events`
- All other `BaseAggregate` methods and attributes

Supported decorators: `aggregate`, `entity`, `value_object`, `command`,
`event`, `domain_service`, `command_handler`, `event_handler`,
`application_service`, `subscriber`, `projection`, `projector`,
`repository`, `database_model`, `email`.

Both `@domain.aggregate` (bare) and `@domain.aggregate()` (called) forms
are detected.

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

- **`auto_add_id_field=False`** — The plugin does not inspect decorator
  arguments. If you pass `auto_add_id_field=False` to `@domain.aggregate`,
  the plugin still injects `id`. Use `# type: ignore[attr-defined]` if needed.

- **Autocomplete for injected methods** — While mypy correctly type-checks
  injected base class methods, some IDE autocomplete engines may not show them
  in suggestions because the base class is not in the explicit MRO.

- **Explicit inheritance** — If you already inherit from a base class
  (e.g. `class Order(BaseAggregate):`), the plugin detects this and skips
  injection to avoid duplicates.
