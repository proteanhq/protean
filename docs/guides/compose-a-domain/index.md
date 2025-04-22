# Compose a Domain

In Protean, the Domain serves as the central composition root of your application, providing a structured way to organize and manage your domain elements, configuration, and adapters.

## Domain as a Composition Root

The Domain acts as a composition root, bringing together all the essential components of your application. It provides a centralized location where all elements are registered, configured, and made available for use throughout your application. This centralization simplifies dependency management and promotes a more maintainable architecture.

### Key Responsibilities

#### Element Management

The Domain maintains a registry of all domain elements, including entities, value objects, repositories, services, and other components. This registry serves as a catalog that makes these elements discoverable and accessible throughout your application.

#### Configuration Storage

Your Domain stores configuration settings that define how your application behaves. These settings can include database connection parameters, feature flags, environment-specific values, and other application-wide settings. Read more at [Configuration](../configuration.md).

#### Adapter Activation

The Domain manages the lifecycle of adapters, which are components that connect your application to external systems and services. This includes activating the appropriate adapters based on your configuration and ensuring they are properly initialized.

#### Automatic Element Collection

Protean's Domain leverages Python decorators to automatically collect and register domain elements. By simply applying the appropriate decorator to your classes, they are automatically discovered and registered with the Domain during initialization.

```python
from protean import Domain

domain = Domain()
...

@domain.aggregage
class User:
    # Aggregate definition...
```

This declarative approach reduces boilerplate code and makes your domain model more expressive and maintainable.

## Parameters

The `Domain` constructor accepts several parameters that control how the domain is initialized and configured:

### `root_path`

Optional. Defaults to `None`.

The path to the folder containing the domain file. This parameter is optional and follows a resolution priority:

1. Explicit `root_path` parameter if provided
2. `DOMAIN_ROOT_PATH` environment variable if set
3. Auto-detection of caller's file location
4. Current working directory as last resort

The `root_path` is used for finding configuration files and traversing domain files.

```python
# Explicit root path
domain = Domain(root_path="/path/to/domain")

# Using environment variable
# export DOMAIN_ROOT_PATH="/path/to/domain"
domain = Domain()  # Will use DOMAIN_ROOT_PATH

# Auto-detection (uses the directory of the file where Domain is instantiated)
domain = Domain()
```

This is handled even under various execution contexts:

- Standard Python scripts
- Jupyter/IPython notebooks
- REPL/interactive shell
- Frozen/PyInstaller applications

### `name`

The name of the domain. 

Optional and defaults to the module name where the domain is instantiated.

The domain name is used in various contexts, including event type construction and logging.

```python
# Explicit name
domain = Domain(name="ecommerce")

# Default name (uses module name)
domain = Domain()  # If in module 'my_app', name will be 'my_app'
```

### `config`

An optional configuration dictionary that overrides the default configuration and any configuration loaded from files.

If not provided, configuration is loaded from `.domain.toml`, `domain.toml`, or `pyproject.toml` files in the domain folder or its parent directories.

```python
# Explicit configuration
domain = Domain(config={
    "identity_strategy": "UUID",
    "databases": {
        "default": {"provider": "postgres", "url": "postgresql://user:pass@localhost/db"}
    }
})

# Default configuration (loads from TOML files if available)
domain = Domain()
```

Refer to [Configuration](../configuration.md) to understand configuration file structure and parameters.

### `identity_function`

An optional function to generate identities for domain objects. This parameter is required when the `identity_strategy` in configuration is set to `FUNCTION`.

```python
# Custom identity function
def generate_id():
    # Custom ID generation logic
    return "custom-id-" + str(random.randint(1000, 9999))

# Using custom identity function
domain = Domain(
    config={"identity_strategy": "FUNCTION"},
    identity_function=generate_id
)
```

## In This Section

- [Register Elements](./register-elements.md) - Explore methods for registering domain elements
- [Initialize Domain](./initialize-domain.md) - Understand how to set up and initialize a new domain
- [Element Decorators](./element-decorators.md) - Learn about using decorators to automatically register domain elements
- [Activate Domain](./activate-domain.md) - Understand how to activate a domain and its components
- [When to Compose a Domain](./when-to-compose.md) - Learn about the appropriate timing and scenarios for composing a domain
