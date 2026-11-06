# Diagnose init-time and runtime failures by code

Some failures cannot be caught by static analysis: they depend on what you pass
to a runtime accessor, or on calling one before `domain.init()` has run.
Protean raises these failures as exceptions, each with a stable **code**
alongside its prose message. An operator or an agent that catches one gets the
same machine-readable rationale and fix as a `protean check` finding.

These are the `kind = "raise"` codes. They are distinct from the `kind =
"lint"` codes that `protean check` reports at design time. The [Fitness
Function Catalog](fitness-functions.md) lists those lint codes. Protean keeps
both sets in one registry, `protean.ir.diagnostics`. Each code is a public
identifier you can rely on: renaming or removing one is a breaking change.

A few of these failures *are* statically detectable (a duplicate database
model, two elements sharing a name). They stay `raise`-only for now. Because
both sets share one registry, a future `protean check` rule can report them at
design time under the same code.

## Reading a coded exception

A coded exception exposes these attributes:

??? example "The domain this example uses"

    ```python
    --8<-- "reference/init-diagnostics/001.py:domain"
    ```

```python
--8<-- "reference/init-diagnostics/001.py:coded_exception"
```

`code`, `codes`, and `location` survive a pickle round-trip. The code therefore
stays intact when an exception crosses the outbox or broker boundary. An
exception raised without a code leaves `code`, `location`, `rationale`, and
`fix` as `None` and `codes` empty, so existing `raise` sites are unaffected.

One raise can carry more than one code. When several invariants fail together,
the single `ValidationError` lists each distinct code once in `codes`. If the
failures carry different codes, `code` is `None`. No single code names the
failure. With exactly one distinct code, `code` holds it and `rationale`/`fix`
resolve from it, even when several invariants failed with that same code.

## What severity does each code carry?

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

**Why.** A short element name can match more than one registered element. The
domain then cannot resolve the name to a single element, so the lookup is
ambiguous.

**Fix.** Look the element up by its fully qualified name to disambiguate, or rename one
of the colliding elements.

### CONFIG_ELEMENT_NOT_REGISTERED { #config-element-not-registered }

| | |
|---|---|
| **Category** | `configuration` |
| **Level** | `error` |
| **Exception** | `ConfigurationError` |
| **Raised by** | `Domain._get_element_by_name`, `Domain._get_element_by_fully_qualified_name` |

**Why.** The domain resolves a name only to an element registered with it. An
unregistered name has nothing to resolve to.

**Fix.** Register the element with the domain before you look it up, or correct
the name to a registered one.

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

### CONFIG_INVALID_FIELD_DEFAULTS { #config-invalid-field-defaults }

| | |
|---|---|
| **Category** | `configuration` |
| **Level** | `error` |
| **Exception** | `ConfigurationError` |
| **Raised by** | `Config2._validate_field_defaults` |

**Why.** `field_defaults.sanitize` sets whether Protean cleans String and Text
fields with `sanitize` left unset. If Protean read a malformed value as
`false`, a typo would become a silent fail-open. Protean rejects the value at
load time instead.

**Fix.** Write `[field_defaults]` as a table and give `sanitize` a boolean, one
of the strings `true`/`1`/`yes`/`on`/`false`/`0`/`no`/`off`, or the empty
string. The empty string reads as false, and `${VAR|}` resolves to it when the
variable is unset.

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

**Fix.** Use `cache_for()` to write a cache-backed projection and `view_for()`
to read it. Keep `repository_for()` for provider-backed elements.

### USAGE_DUPLICATE_DATABASE_MODEL { #usage-duplicate-database-model }

| | |
|---|---|
| **Category** | `usage` |
| **Level** | `error` |
| **Exception** | `IncorrectUsageError` |
| **Raised by** | `Domain._register_element` |

**Why.** An aggregate maps to one database model per database. If you register
a second model for the same aggregate and database, the mapping becomes
ambiguous.

**Fix.** Register one database model per aggregate per database, or target a different
database on the duplicate model.

### USAGE_ELEMENT_NOT_REGISTERED { #usage-element-not-registered }

| | |
|---|---|
| **Category** | `usage` |
| **Level** | `error` |
| **Exception** | `IncorrectUsageError` |
| **Raised by** | `Domain.repository_for`, `Domain.view_for`, `Domain.connection_for`, `Domain.create_snapshot`, `Domain.create_snapshots` |

**Why.** A runtime accessor resolves the element you pass against the registry.
The registry has no entry for an unregistered element, or for a name string
passed instead of the class.

**Fix.** Register the element with the domain first. Then pass the registered
element class to the accessor.

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

An operation the framework does not support for the given element.

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

## Invariants

A business rule declared with `@invariant.pre` or `@invariant.post` did not
hold at runtime. The `ValidationError` still carries its errors dict. It also
carries the code below, or the code you passed as `@invariant.post(code=...)`.
When several invariants fail together, `codes` lists each distinct code once.

### INVARIANT_PRE_FAILED { #invariant-pre-failed }

| | |
|---|---|
| **Category** | `invariants` |
| **Level** | `error` |
| **Exception** | `ValidationError` |
| **Raised by** | an aggregate, entity, or domain service `@invariant.pre` check |

**Why.** An `@invariant.pre` guards the required state before an aggregate,
entity, or domain service is changed or run. Your code attempted the change
while that guard did not hold.

**Fix.** Satisfy the pre-condition first, or catch the `ValidationError` and correct
the input. The error messages name what failed.

### INVARIANT_POST_FAILED { #invariant-post-failed }

| | |
|---|---|
| **Category** | `invariants` |
| **Level** | `error` |
| **Exception** | `ValidationError` |
| **Raised by** | an aggregate, entity, or domain service `@invariant.post` check |

**Why.** An `@invariant.post` condition must hold once an aggregate, entity, or
domain service is built, changed, or run. The resulting state broke that
condition.

**Fix.** Correct the state so the post-condition holds, or catch the
`ValidationError`. The error messages name what failed.

### VALUE_OBJECT_INVARIANT_FAILED { #value-object-invariant-failed }

| | |
|---|---|
| **Category** | `invariants` |
| **Level** | `error` |
| **Exception** | `ValidationError` |
| **Raised by** | a value object invariant check at construction |

**Why.** A value object validates its invariants at construction and is immutable
afterward; the values it was built from broke one of those invariants.

**Fix.** Build the value object from values that satisfy its invariants, or catch the
`ValidationError`. The error messages name what failed.
