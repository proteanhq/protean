# Activate the domain

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Once a domain is initialized, the next step is to activate it.

A `Domain` in protean is always associated with a domain context, which can be
used to bind an domain object implicitly to the current thread or greenlet. We
refer to the act of binding the domain object as **activating the domain**.

## Domain Context

A Protean Domain object has attributes, such as config, that are useful to
access within domain elements. However, importing the domain instance within
the modules in your project is prone to circular import issues.

Protean solves this issue with the domain context. Rather than passing the
domain around to each method, or referring to a domain directly, you can use
the `current_domain` proxy instead. The `current_domain` proxy,
which points to the domain handling the current activity.

The `DomainContext` holds the active domain object for the duration of a
thread's execution. The domain context tracks the domain-level data during the
lifetime of a domain object. Protean uses the domain context while it processes
handlers, CLI commands, or other activities.

## Activating the Domain Context

A Protean domain is activated close to the application's entrypoint, like an
API request. In many other cases, like Protean's server processing commands and
events, or the CLI accessing the domain, Protean automatically activates a
domain context for the duration of the task.

You activate a domain by pushing up its context to the top of the domain stack:

### With Context Manager
Protean provides a context manager. You run the domain operations inside
its block.

```python hl_lines="18-20"
--8<-- "guides/compose-a-domain/018.py:full"
```

Subsequent calls to `current_domain` will return the currently active domain.
When the task completes, the context manager pops the context and resets the
domain stack to its original state.

This is a convenient pattern to use with most API frameworks. The domain’s
context is pushed up at the beginning of a request and popped out
once the request is processed.

### Manually

You can also activate the context manually by using the `push` and `pop`
methods of the domain context:

```python
--8<-- "guides/compose-a-domain/activate-domain/001.py:manual"
```

!!! warning
    When you activate the context manually, call context.pop() after the task
    completes. Otherwise, the context can leak across threads.

### Check whether a domain is active

Code that can run both inside and outside a domain context can ask with
`has_domain_context()`. It returns `True` when a domain context is active and
`False` otherwise, and it never warns:

```python
--8<-- "guides/compose-a-domain/activate-domain/003.py:check"
```

`bool(current_domain)` gives the same answer, but outside a domain context it
also emits a "Working outside of domain context" warning.

## Storing Data

The domain context also provides a `g` object for storing data. It is a simple
namespace object that has the same lifetime as an domain context.

!!! note
    The `g` name stands for "global", but that is referring to the data
    being global within a context. The data on `g` is lost after the context
    ends, and it is not an appropriate place to store data between domain
    calls. Use a session or a database to store data across domain model calls.

A common use for g is to create a resource once and close it at the end of a
domain call.

1. `get_X()` creates resource X if it does not exist, caching it as g.X.

2. `teardown_X()` closes or otherwise deallocates the resource if it exists.
It is registered as a `teardown_domain_context()` handler.

With the `get_X()` and `teardown_X()` pattern, you can, for example, keep a
file connection open for the lifetime of a domain call:

```python
--8<-- "guides/compose-a-domain/activate-domain/002.py:g-resource"
```

Now, every call to `get_log()` during the domain call returns the same file
object. The teardown handler closes the file object automatically at the end
of processing.
