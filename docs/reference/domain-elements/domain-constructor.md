# Domain Constructor

The `Domain` class is the central composition root of a Protean application.
It manages element registration, configuration, and adapter lifecycle.

```python
--8<-- "reference/domain-elements/domain-constructor/001.py:constructor"
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
--8<-- "reference/domain-elements/domain-constructor/002.py:explicit"

--8<-- "reference/domain-elements/domain-constructor/003.py:environment"

--8<-- "reference/domain-elements/domain-constructor/004.py:auto"
```

### `name`

**Type:** `str | None` &nbsp; **Default:** caller's module name

The name of the domain, used in event type construction, logging, and
stream naming.

```python
--8<-- "reference/domain-elements/domain-constructor/005.py:explicit"

--8<-- "reference/domain-elements/domain-constructor/006.py:default"
```

### `config`

**Type:** `dict | None` &nbsp; **Default:** `None`

An optional configuration dictionary that overrides default configuration
and any configuration loaded from files.

If not provided, configuration is loaded from `.domain.toml`, `domain.toml`,
or `pyproject.toml` files in the domain folder or its parent directories.

```python
# fragment
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
--8<-- "reference/domain-elements/domain-constructor/007.py:identity_function"
```
