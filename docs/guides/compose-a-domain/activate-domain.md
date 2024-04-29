# Activate the domain

A `Domain` in protean is always associated with a domain context, which can be
used to bind an domain object implicitly to the current thread or greenlet. We
refer to the act of binding the domain object as **activating the domain**.

<!-- FIXME Insert link to fullblown DomainContext documentation -->
A `DomainContext` helps manage the active domain object for the duration of a
thread's execution. It also provides a namespace for storing data for the
duration a domain context is active. 

You activate a domain by pushing up its context to the top of the domain stack. 

## Using a Context Manager
Protean provides a helpful context manager to nest the domain operations
under.

```Python hl_lines="18-21"
{! docs_src/guides/composing-a-domain/018.py !}
```

Subsequent calls to `current_domain` will return the currently active domain.
Once the task has been completed, the domain stack is reset to its original
state after popping the context.

This is a convenient pattern to use in conjunction with most API frameworks.
The domain’s context is pushed up at the beginning of a request and popped out 
once the request is processed.

## Without the Context Manager

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
