# Init-time and Runtime Diagnostics

Some failures cannot be caught by static analysis: they depend on what you pass
to a runtime accessor, or on calling one before `domain.init()` has run. Protean
raises these as exceptions, and each one carries a stable **code** alongside its
prose message, so an operator or an agent catching the exception gets the same
machine-readable rationale and fix that a `protean check` finding carries.

These are the `kind = "raise"` codes. They are distinct from the
[Fitness Function Catalog](fitness-functions.md), which lists the
`kind = "lint"` codes that `protean check` reports at design time. Both sets
live in one registry, `protean.ir.diagnostics`, so a code is a public identifier
you can rely on: renaming or removing one is a breaking change.

A few of these failures *are* statically detectable (a duplicate database model,
two elements sharing a name). They stay `raise`-only for now; the shared
registry keeps the door open for a future `protean check` rule to surface them at
design time under the same code.

## Reading a coded exception

Every coded exception exposes four attributes:

```python
from protean.exceptions import IncorrectUsageError

try:
    domain.view_for(SomeAggregate)
except IncorrectUsageError as exc:
    print(exc.code)       # "USAGE_NOT_A_PROJECTION"
    print(exc.location)   # "Domain.view_for"
    print(exc.rationale)  # why it fired, from the registry
    print(exc.fix)        # how to fix it, from the registry
```

`code` and `location` survive a pickle round-trip, so the code is intact when an
exception crosses the outbox or broker boundary. An exception raised without a
code leaves all four attributes `None`, so existing `raise` sites are unaffected.

## Severity levels

Every code here is an `error`: the operation cannot proceed. (Advisory
`warning`/`info` levels belong to the lint codes in the fitness-function
catalog.)

---

## Configuration

Failures resolving configuration or looking up a registered element by name.

### CONFIG_AMBIGUOUS_ELEMENT_NAME { #config-ambiguous-element-name }

| | |
|---|---|
| **Category** | `configuration` |
| **Level** | `error` |
| **Exception** | `ConfigurationError` |
| **Raised by** | `Domain._get_element_by_name` |

**Why.** A short element name that matches more than one registered element cannot be
resolved to a single element, so the lookup is ambiguous.

**Fix.** Look the element up by its fully qualified name to disambiguate, or rename one
of the colliding elements.

### CONFIG_ELEMENT_NOT_REGISTERED { #config-element-not-registered }

| | |
|---|---|
| **Category** | `configuration` |
| **Level** | `error` |
| **Exception** | `ConfigurationError` |
| **Raised by** | `Domain._get_element_by_name`, `Domain._get_element_by_fully_qualified_name` |

**Why.** Resolving an element by name requires it to be registered with the domain; an
unregistered name has nothing to resolve to.

**Fix.** Register the element with the domain before it is looked up, or correct the
name to one that is registered.

### CONFIG_EVENT_STORE_NOT_INITIALIZED { #config-event-store-not-initialized }

| | |
|---|---|
| **Category** | `configuration` |
| **Level** | `error` |
| **Exception** | `ConfigurationError` |
| **Raised by** | `Domain._require_event_store` |

**Why.** The event store is wired during `domain.init()`; using it before then leaves
the store unset.

**Fix.** Call `domain.init()` before using the event store.

### CONFIG_UNRESOLVED_ENV_VAR { #config-unresolved-env-var }

| | |
|---|---|
| **Category** | `configuration` |
| **Level** | `error` |
| **Exception** | `ConfigurationError` |
| **Raised by** | `Config2._replace_env_var` |

**Why.** A `${VAR}` placeholder in configuration is substituted from the environment at
load time; with the variable unset and no default given, it resolves to
nothing.

**Fix.** Set the environment variable in the runtime environment, or give the
placeholder a default with `${VAR|default}`.

## Usage

Runtime misuse of an accessor: passing the wrong kind of element, a name string
instead of the class, or an unregistered element.

### USAGE_CACHE_BACKED_NO_REPOSITORY { #usage-cache-backed-no-repository }

| | |
|---|---|
| **Category** | `usage` |
| **Level** | `error` |
| **Exception** | `IncorrectUsageError` |
| **Raised by** | `Domain.repository_for` |

**Why.** A cache-backed projection is served from a cache, not a provider, so it has no
repository.

**Fix.** Use `cache_for()` to write and `view_for()` to read a cache-backed projection;
`repository_for()` is for provider-backed elements.

### USAGE_DUPLICATE_DATABASE_MODEL { #usage-duplicate-database-model }

| | |
|---|---|
| **Category** | `usage` |
| **Level** | `error` |
| **Exception** | `IncorrectUsageError` |
| **Raised by** | `Domain._register_element` |

**Why.** An aggregate maps to one database model per database; registering a second
model for the same aggregate and database makes the mapping ambiguous.

**Fix.** Register one database model per aggregate per database, or target a different
database on the duplicate model.

### USAGE_ELEMENT_NOT_REGISTERED { #usage-element-not-registered }

| | |
|---|---|
| **Category** | `usage` |
| **Level** | `error` |
| **Exception** | `IncorrectUsageError` |
| **Raised by** | `Domain.repository_for`, `Domain.view_for`, `Domain.connection_for`, `Domain.create_snapshot`, `Domain.create_snapshots` |

**Why.** A runtime accessor resolves the element it is given against the registry; an
unregistered element, or a name string instead of the class, has no entry to
resolve.

**Fix.** Pass a registered element class to the accessor, and register the element with
the domain first.

### USAGE_ENRICHER_NOT_CALLABLE { #usage-enricher-not-callable }

| | |
|---|---|
| **Category** | `usage` |
| **Level** | `error` |
| **Exception** | `IncorrectUsageError` |
| **Raised by** | `Domain.register_event_enricher`, `Domain.register_command_enricher`, `Domain.register_aggregate_enricher` |

**Why.** An enricher is invoked to augment a message or aggregate, so it has to be
callable; a non-callable value cannot be invoked.

**Fix.** Register a callable (a function or a callable object) as the enricher.

### USAGE_NOT_A_PROJECTION { #usage-not-a-projection }

| | |
|---|---|
| **Category** | `usage` |
| **Level** | `error` |
| **Exception** | `IncorrectUsageError` |
| **Raised by** | `Domain.view_for`, `Domain.connection_for` |

**Why.** `view_for` and `connection_for` operate on projections; an element of another
type has no read view or projection connection.

**Fix.** Call the accessor with a projection, or use the accessor that matches the
element's type.

### USAGE_UNKNOWN_ELEMENT_TYPE { #usage-unknown-element-type }

| | |
|---|---|
| **Category** | `usage` |
| **Level** | `error` |
| **Exception** | `IncorrectUsageError` |
| **Raised by** | `Domain.factory_for` |

**Why.** The domain builds elements through a fixed set of type factories; a type
outside that set has no factory to build it.

**Fix.** Use one of the supported domain element types.

## Unsupported

An operation the framework does not support for the element it was given.

### UNSUPPORTED_ELEMENT_CLASS { #unsupported-element-class }

| | |
|---|---|
| **Category** | `unsupported` |
| **Level** | `error` |
| **Exception** | `NotSupportedError` |
| **Raised by** | `Domain.register` |

**Why.** Only classes carrying a domain `element_type` can be registered; a plain class
has no element type for the domain to register.

**Fix.** Decorate the class as a domain element (e.g. `@domain.aggregate`) before
registering it, or register a valid element class.
