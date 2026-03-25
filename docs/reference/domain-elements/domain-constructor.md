# Domain Constructor

The `Domain` class is the central composition root of a Protean application.
It manages element registration, configuration, and adapter lifecycle.

```python
from protean import Domain

domain = Domain(
    root_path=None,
    name=None,
    config=None,
    identity_function=None,
)
```

## Parameters

### `root_path`

**Type:** `str | None` &nbsp; **Default:** `None`

The path to the folder containing the domain file. Used for finding
configuration files and traversing domain element modules.

Resolution priority:

1. Explicit `root_path` parameter if provided
2. `DOMAIN_ROOT_PATH` environment variable if set
3. Auto-detection of caller's file location
4. Current working directory as last resort

Works under all execution contexts: standard scripts, Jupyter/IPython
notebooks, REPL, and frozen/PyInstaller applications.

```python
# Explicit root path
domain = Domain(root_path="/path/to/domain")

# Using environment variable
# export DOMAIN_ROOT_PATH="/path/to/domain"
domain = Domain()  # Will use DOMAIN_ROOT_PATH

# Auto-detection (uses the directory of the file where Domain is instantiated)
domain = Domain()
```

### `name`

**Type:** `str | None` &nbsp; **Default:** caller's module name

The name of the domain, used in event type construction, logging, and
stream naming.

```python
# Explicit name
domain = Domain(name="ecommerce")

# Default name (uses module name)
domain = Domain()  # If in module 'my_app', name will be 'my_app'
```

### `config`

**Type:** `dict | None` &nbsp; **Default:** `None`

An optional configuration dictionary that overrides default configuration
and any configuration loaded from files.

If not provided, configuration is loaded from `.domain.toml`, `domain.toml`,
or `pyproject.toml` files in the domain folder or its parent directories.

```python
domain = Domain(config={
    "identity_strategy": "uuid",
    "databases": {
        "default": {
            "provider": "postgresql",
            "database_uri": "postgresql://user:pass@localhost/db",
        }
    }
})
```

See [Configuration](../configuration/index.md) for the full list of
configuration parameters.

### `identity_function`

**Type:** `Callable | None` &nbsp; **Default:** `None`

A custom function to generate identities for domain objects. Required when
`identity_strategy` is set to `"function"` in configuration.

```python
def generate_id():
    return "custom-id-" + str(random.randint(1000, 9999))

domain = Domain(
    config={"identity_strategy": "function"},
    identity_function=generate_id,
)
```
