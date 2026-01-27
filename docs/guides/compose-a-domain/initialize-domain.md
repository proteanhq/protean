# Initialize the domain

The domain is initialized by calling the `init` method.

```python
domain.init()
```

## `Domain.init()`

A call to `init` does the following:

### 1. Traverse the domain model

By default, Protean traverses the directory structure under the domain file
to discover domain elements. You can control this behavior with the `traverse`
flag:

```python
domain.init(traverse=False)
```

If you choose to not traverse, Protean will not be able to detect domain
elements automatically. ***You are responsible for registering each element
with the domain explicitly***.

### 2. Construct the object graph

Protean constructs a graph of all elements registered with a domain and
exposes them in a registry.

```python hl_lines="27-35"
{! docs_src/guides/composing-a-domain/016.py !}
```

### 3. Initialize dependencies

Calling `domain.init()` establishes connectivity with the underlying infra,
testing access, and making them available for use by the rest of the system.

By default, a protean domain is configured to use in-memory replacements for
infrastructure, like databases, brokers, and caches. They are useful for
testing and prototyping. But for production purposes, you will want to choose
a database that actually persists data.

```python hl_lines="5-9 11"
{! docs_src/guides/composing-a-domain/017.py !}
```

In the example above, the domain activates an SQLite database repository and
makes it available for domain elements for further use.

<!-- FIXME Add link to accessing active/configured dependencies -->
Refer to [Configuration handling](../essentials/configuration.md) to understand the different ways to configure
the domain.

### 4. Validate Domain Model

In the final part of domain initialization, Protean performs additional setup
tasks on domain elements and also conducts various checks to ensure the domain
model is specified correctly.

Examples of checks include:

1. Resolving references that were specified as Strings, like:

```python
@domain.entity(part_of="User")
class Account:
    ...
```

1. Setting up Aggregate clusters and their shared settings. The object graph
constructed earlier is used to homogenize settings across all elements under
an aggregate, like the stream category and database provider.

1. Constructing a map of command and event types to reference when processing
incoming messages later.

1. Various checks and validations to ensure the domain structure is valid.
