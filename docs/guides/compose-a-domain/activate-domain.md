# Activate the domain

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

The `DomainContext` helps manage the active domain object for the duration of a
thread's execution. The domain context keeps track of the domain-level data
during the lifetime of a domain object, and is used while processing handlers,
CLI commands, or other activities. 

## Storing Data

The domain context also provides a `g` object for storing data. It is a simple
namespace object that has the same lifetime as an domain context.

!!! note
    The `g` name stands for "global", but that is referring to the data
    being global within a context. The data on `g` is lost after the context
    ends, and it is not an appropriate place to store data between domain
    calls. Use a session or a database to store data across domain model calls.

A common use for g is to manage resources during a domain call.

1. `get_X()` creates resource X if it does not exist, caching it as g.X.

2. `teardown_X()` closes or otherwise deallocates the resource if it exists.
It is registered as a `teardown_domain_context()` handler.

Using this pattern, you can, for example, manage a file connection for the
lifetime of a domain call:

```python
from protean.globals import g

def get_log():
    if 'log' not in g:
        g.log = open_log_file()

    return g.log

@domain.teardown_appcontext
def teardown_log_file(exception):
    file_obj = g.pop('log', None)

    if not file_obj.closed:
        file_obj.close()
```

Now, every call to `get_log()` during the domain call will return the same file
object, and it will be closed automatically at the end of processing.

## Pushing up the Domain Context

A Protean domain is activated close to the application's entrypoint, like an
API request. In many other cases, like Protean's server processing commands and
events, or the CLI accessing the domain, Protean automatically activates a
domain context for the duration of the task.

You activate a domain by pushing up its context to the top of the domain stack:

### With Context Manager
Protean provides a helpful context manager to nest the domain operations
under.

```python hl_lines="18-21"
{! docs_src/guides/composing-a-domain/018.py !}
```

Subsequent calls to `current_domain` will return the currently active domain.
Once the task has been completed, the domain stack is reset to its original
state after popping the context.

This is a convenient pattern to use in conjunction with most API frameworks.
The domain’s context is pushed up at the beginning of a request and popped out 
once the request is processed.

### Manually

You can also activate the context manually by using the `push` and `pop`
methods of the domain context:

```python
context = domain.domain_context()

# Activate the domain
context.push()

# Do something interesting
# ...
# ...

# Reset domain stack when done
context.pop()
```

!!! warning
    If you do activate context manually, ensure you call context.pop() once the
    task has been completed to prevent context leakage across threads.
