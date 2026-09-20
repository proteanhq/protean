# Message Enrichment Anti-Patterns

## Wrong enricher signature

Command and event enrichers have different signatures. Mixing them up fails.

```python
# WRONG — event enricher missing the aggregate parameter
@domain.event_enricher
def add_ctx(event):
    return {...}

# RIGHT
@domain.event_enricher
def add_ctx(event, aggregate):
    return {...}

# Command enrichers take only the command
@domain.command_enricher
def add_ctx(command):
    return {...}
```

## Mutating the message

Enrichers return data; they must not reach into the message and mutate it.

```python
# WRONG
@domain.command_enricher
def add_ctx(command):
    command._metadata.extensions["request_id"] = g.request_id
    return None

# RIGHT
@domain.command_enricher
def add_ctx(command):
    return {"request_id": getattr(g, "request_id", None)}
```

## Unsafe context access aborts the message

An enricher that raises stops the command from being processed (or the event from
being appended). Reading a missing attribute off `g` is the usual culprit.

```python
# WRONG — raises AttributeError when request_id isn't set
@domain.command_enricher
def add_ctx(command):
    return {"request_id": g.request_id}

# RIGHT — degrade gracefully
@domain.command_enricher
def add_ctx(command):
    return {"request_id": getattr(g, "request_id", None)}
```

## Doing work in an enricher

Enrichers run on the hot path of every command/event. They should read context and
return a dict — not load aggregates, hit the database, or call services.

```python
# WRONG — I/O in an enricher
@domain.event_enricher
def add_ctx(event, aggregate):
    user = current_domain.repository_for(User).get(aggregate.created_by)  # NO
    return {"user_email": user.email}
```

Capture what you need into `g` earlier (e.g. in middleware) and read it here.

## Business data in extensions

`metadata.extensions` is for cross-cutting metadata (tenant, request, actor,
correlation). Domain payload belongs in the command/event fields, not extensions.
