# Object Model

A domain model in Protean is composed with various types of domain elements,
all of which have a common structure and share a few behavioral traits. This
document outlines generic aspects that apply to every domain element.

## `Element` Base class

`Element` is a base class inherited by all domain elements. Currently, it does
not have any data structures or behavior associated with it.

## Configuration Options

Additional options can be passed to a domain element in two ways:

- **`Meta` inner class**

You can specify options within a nested inner class called `Meta`:

```python hl_lines="13-14"
{! docs_src/guides/composing-a-domain/020.py !}
```

- **Decorator Parameters**

You can also pass options as parameters to the decorator:

```python hl_lines="7"
{! docs_src/guides/composing-a-domain/021.py !}
```
