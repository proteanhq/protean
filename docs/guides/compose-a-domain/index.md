# Set Up the Domain

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

The `Domain` is the central composition root of a Protean application. It
registers domain elements, loads configuration, and manages adapter
lifecycle. Every Protean project starts by creating a `Domain` instance.

## Creating a Domain

The simplest way to create a domain:

```python
from protean import Domain

domain = Domain()
```

Protean auto-detects the root path from the caller's file location and
searches that directory and its parent directories for configuration in
`.domain.toml`, `domain.toml`, or `pyproject.toml`.

For named domains or explicit configuration:

```python
domain = Domain(
    name="ecommerce",
    config={
        "databases": {
            "default": {
                "provider": "postgresql",
                "database_uri": "postgresql://localhost/ecommerce",
            }
        }
    },
)
```

For the full list of constructor parameters, see
[Domain Constructor Reference](../../reference/domain-elements/domain-constructor.md).
For configuration options, see
[Configuration](../../reference/configuration/index.md).

## What's in This Section

### [Register Elements](./register-elements.md)

Register domain elements with decorators or manual registration.

### [Initialize Domain](./initialize-domain.md)

Call `domain.init()` to resolve references, validate the domain, and
connect adapters.

### [Activate Domain](./activate-domain.md)

Push a domain context to make `current_domain` and the `g` object available.

### [When to Compose](./when-to-compose.md)

When to call `domain.init()` and push the context in FastAPI, Flask,
scripts, and the Protean server.

### [Configure for Production](./production-configuration.md)

Environment overlays, environment variable substitution, adapter
selection, and dual-mode testing configuration.

### [Inspecting the IR](./inspecting-the-ir.md)

Generate and explore the domain's Intermediate Representation.

### [Schema Generation](./schema-generation.md)

Generate JSON Schema files for domain elements.

## Related

- [Domain Constructor Reference](../../reference/domain-elements/domain-constructor.md)
  -- Full parameter documentation.
- [Element Decorators](../../reference/domain-elements/element-decorators.md)
  -- All decorators and their options.
- [Object Model](../../reference/domain-elements/object-model.md)
  -- Common structure and traits shared by all domain elements.
- [Compatibility Checking](../compatibility-checking.md)
  -- Detect breaking changes with IR diffing, hooks, and CI.
