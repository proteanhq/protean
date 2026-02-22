# Register elements

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


The domain object is used by the domain's elements to register themselves with
the domain.

## With decorators

```python hl_lines="7-11"
{! docs_src/guides/compose-a-domain/002.py !}
```

A full list of domain decorators along with examples are available in the
[decorators](../../reference/domain-elements/element-decorators.md) section.

## Passing additional options

There might be additional options you will pass in a `Meta` inner class,
depending upon the element being registered.

```python hl_lines="7"
{! docs_src/guides/compose-a-domain/015.py !}
```

In the above example, the `User` aggregate's default stream category **`user`**
is customized to **`account`**.

Review the [object model](../../reference/domain-elements/object-model.md) to understand
multiple ways to pass these options. Refer to each domain element's
documentation to understand the additional options supported by that element.

<!--FIXME Add info on how to get to each domain element -->

## Explicit registration

You can also choose to register elements manually.

```python hl_lines="8-11 14"
{! docs_src/guides/compose-a-domain/014.py !}
```

Note that the `User` class has been subclassed from `BaseAggregate`. That is
how Protean understands the kind of domain element being registered. Each type
of element in Protean has a distinct base class of its own.

Also, additional options are now passed in the `register` call to the domain.

<!-- FIXME Add link to base classes -->
