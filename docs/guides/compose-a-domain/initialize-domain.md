# Initialize the domain

The domain is initialized by calling the `init` method. 

```python
domain.init()
```

A call to `init` does the following:

## 1. Traverse the domain model

By default, Protean traverses the directory structure under the domain file
to discover domain elements. You can control this behavior with the `traverse`
flag:

```python
domain.init(traverse=False)
```

If you choose to not traverse, Protean will not be able to detect domain
elements automatically. ***You are responsible for registering each element
with the domain explicitly***.

## 2. Construct the object graph

Protean constructs a graph of all elements registered with a domain and
exposes them in a registry.

```python hl_lines="27-35"
{! docs_src/guides/composing-a-domain/016.py !}
```

## 3. Inject dependencies

By default, a protean domain is configured to use in-memory replacements for
infrastructure, like databases, brokers, and caches. They are useful for
testing and prototyping. But for production purposes, you will want to choose
a database that actually persists data.

Calling `domain.init()` establishes connectivity with the underlying infra,
testing access, and making them available for use by the rest of the system. 

```python hl_lines="5-9 11"
{! docs_src/guides/composing-a-domain/017.py !}
```

In the example above, the domain activates an SQLite database repository and
makes it available for domain elements for further use.

<!-- FIXME Add link to accessing active/configured dependencies -->
Refer to [Configuration Handling](configuration.md) to understand the different ways to configure
the domain.
