# Object Model

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Domain elements in Protean have a common structure and share a few behavioral
traits.

## Meta Options

Protean elements have a `meta_` attribute that holds the configuration options
specified for the element. 

Options are passed as parameters to the element decorator:

```python hl_lines="7"
{! docs_src/guides/composing-a-domain/021.py !}
```

```python
In [1]: User.meta_
Out[1]: 
{'database_model': None,
 'stream_category': 'user',
 'auto_add_id_field': True,
 'fact_events': False,
 'abstract': False,
 'schema_name': 'user',
 'aggregate_cluster': User,
 'is_event_sourced': False,
 'provider': 'default'}
```

### `abstract`

`abstract` is a common meta attribute available on all elements. An element
that is marked abstract cannot be instantiated.

!!!note
    Field orders are preserved in container elements.

## Reflection

Protean provides reflection methods to explore container elements. Each of the
below methods accept a element or an instance of one.

### `has_fields`

Returns `True` if the element encloses fields.

### `fields`

Return a tuple of fields in the element, both explicitly defined and internally
added.

Raises `IncorrectUsageError` if called on non-container elements like
Application Services or Command Handlers.

### `declared_fields`

Return a tuple of the explicitly declared fields.

### `data_fields`

Return a tuple describing the data fields in this element. Does not include
metadata.

Raises `IncorrectUsageError` if called on non-container elements like
Application Services or Command Handlers.

### `has_association_fields`

Returns `True` if element contains associations.

### `association_fields`

Return a tuple of the association fields.

Raises `IncorrectUsageError` if called on non-container elements.

### `id_field`

Return the identity field of this element, or `None` if there is no identity
field.

### `has_id_field`

Returns `True` if the element has an identity field.

### `attributes`

Internal. Returns a dictionary of fields that generate a representation of
data for external use.

Attributes include simple field representations of complex fields like
value objects and associations.

Raises `IncorrectUsageError` if called on non-container elements

### `unique_fields`

Return fields marked as unique.

Raises `IncorrectUsageError` if called on non-container elements.
