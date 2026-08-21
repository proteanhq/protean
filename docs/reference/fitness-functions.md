# Fitness Function Catalog

Every diagnostic `protean check` can report, grouped by category. Each entry
lists the rule's category and severity level, why it fires, and how to fix it.

For a task-oriented walkthrough (running the checks, suppressing findings, and
wiring them into CI) see the [Architecture Fitness Functions
guide](../guides/architecture-fitness-functions.md). For the JSON/SARIF shape
of a finding and the CLI flags, see the [`protean check`
reference](cli/check.md).

Each diagnostic carries a stable **code** (e.g. `AGGREGATE_TOO_LARGE`). A code is
a public identifier you can rely on in CI gates, suppression lists, and SARIF
consumers: renaming or removing one is a breaking change. Every code and its
metadata live in one place, `protean.ir.diagnostics`, so what you match on here
is what the tool emits.

## Severity levels

| Level | Meaning |
|-------|---------|
| `warning` | A likely design problem worth addressing. Gates CI at the default `[lint].level = "warn"` floor. |
| `info` | An advisory observation. Never gates CI unless `[lint].level = "info"`. |

Validator **errors** (malformed domains that cannot build an IR) are a
separate, always-fatal class and are not listed here. They always exit `1`.

The coded exceptions raised at init and by runtime accessors (the `kind =
"raise"` codes) are catalogued separately in
[Init-time and Runtime Diagnostics](init-diagnostics.md).

---

## Aggregate Design

Rules that keep aggregates within their consistency boundary and value objects
immutable.

### CROSS_AGGREGATE_REFERENCE { #cross-aggregate-reference }

| | |
|---|---|
| **Category** | `aggregate_design` |
| **Level** | `warning` |

**Why.** Aggregates coordinate other aggregates by identity, not by object
reference (Vernon's Rule 3). A `Reference` to another aggregate's root couples
the two into one object graph and invites a single transaction to span both
clusters.

**Fix.** Hold the other aggregate by its identifier instead of a `Reference`.
Replace `Reference(<Other>)` with an `Identifier` field (for example
`<other>_id: Identifier()`) and load the other aggregate through its own
repository when needed.

### ES_AGGREGATE_NO_EVENTS { #es-aggregate-no-events }

| | |
|---|---|
| **Category** | `aggregate_design` |
| **Level** | `warning` |

**Why.** An event-sourced aggregate reconstitutes its state by replaying its
events. With no events registered it can record no state changes and cannot be
rebuilt from its stream.

**Fix.** Declare at least one domain event with `part_of=<Aggregate>` and raise
it from the aggregate's behaviour, or drop `event_sourced=True` if the aggregate
is not meant to be event-sourced.

### VALUE_OBJECT_MUTABLE_FIELD { #value-object-mutable-field }

| | |
|---|---|
| **Category** | `aggregate_design` |
| **Level** | `warning` |

**Why.** Value objects are compared by value and must be immutable. A `List` or
`Dict` field gives the value object mutable internal state, so two instances that
should be equal can diverge and value equality no longer holds.

**Fix.** Replace the mutable collection with an immutable representation, or move
the collection onto the containing entity or aggregate. If the values form a
concept with its own identity, model them as an entity referenced by the
aggregate instead.

### AGGREGATE_TOO_LARGE { #aggregate-too-large }

| | |
|---|---|
| **Category** | `aggregate_design` |
| **Level** | `info` |

**Why.** A large aggregate is a consistency boundary and contention hotspot;
oversized clusters are hard to keep transactionally consistent.

**Fix.** Split the aggregate into smaller aggregates, or raise
`[lint] aggregate_size_limit` (default `5` entities) if the size is intentional.

### HANDLER_TOO_BROAD { #handler-too-broad }

| | |
|---|---|
| **Category** | `aggregate_design` |
| **Level** | `info` |

**Why.** A handler that handles many message types accretes unrelated
responsibilities and becomes hard to reason about.

**Fix.** Split the handler into focused handlers, or raise
`[lint] handler_breadth_limit` (default `5` message types) if the breadth is
intentional.

### EVENT_WITHOUT_DATA { #event-without-data }

| | |
|---|---|
| **Category** | `aggregate_design` |
| **Level** | `info` |

**Why.** An event with no fields carries no information beyond its name, so
consumers cannot react to what actually changed.

**Fix.** Add fields capturing the state change, or confirm the event is
intentionally a bare signal.

### AGGREGATE_NO_INVARIANTS { #aggregate-no-invariants }

| | |
|---|---|
| **Category** | `aggregate_design` |
| **Level** | `info` |

**Why.** An aggregate is a consistency boundary. With no pre- or post-invariants
it enforces no business rules and is usually an anemic data holder rather than a
true aggregate.

**Fix.** Add one or more `@invariant.pre` or `@invariant.post` methods expressing
the business rules the aggregate must always satisfy, or reconsider whether this
concept is an aggregate at all.

---

## Bounded Context

Rules that preserve independent decomposition and the ports-and-adapters
boundary.

### CIRCULAR_CLUSTER_DEPENDENCY { #circular-cluster-dependency }

| | |
|---|---|
| **Category** | `bounded_context` |
| **Level** | `warning` |

**Why.** Circular identity references between aggregate clusters prevent
independent decomposition, deployment, and event sourcing of the aggregates.

**Fix.** Break the cycle by replacing one direction of the reference with a
domain event or a process manager that coordinates the two aggregates
asynchronously.

### INFRA_IMPORT_IN_DOMAIN { #infra-import-in-domain }

| | |
|---|---|
| **Category** | `bounded_context` |
| **Level** | `warning` (opt-in) |

Off by default. Enable with `[lint].check_infra_imports = true`; the rule then
AST-parses each resolvable domain element's source module.

**Why.** Domain elements must not depend on concrete infrastructure adapters;
importing from `protean.adapters` couples the domain layer to a specific adapter
and breaks the ports-and-adapters boundary.

**Fix.** Remove the `protean.adapters` import from the domain module. Depend on
domain-layer abstractions and let the adapter be wired through the domain's
provider configuration instead.

### ADAPTER_CALL_IN_DOMAIN { #adapter-call-in-domain }

| | |
|---|---|
| **Category** | `bounded_context` |
| **Level** | `warning` (opt-in) |

Off by default. Enable with `[lint].check_adapter_calls = true`. It is gated
separately from `check_infra_imports`, so the two rules switch independently:
this one reads method bodies rather than the module's import list, and catches a
call whose import was aliased or made locally.

**Why.** Domain elements must not depend on concrete infrastructure adapters.
Calling into `protean.adapters` from a domain method couples the domain layer to
a specific adapter at runtime and breaks the ports-and-adapters boundary.

**Fix.** Remove the `protean.adapters` call from the domain method. Depend on
domain-layer abstractions and let the adapter be wired through the domain's
provider configuration instead.

See the [ADAPTER_CALL_IN_DOMAIN reference](../concepts/protean-check/rules/adapter-call-from-domain.md)
for the exact scope and the receivers it resolves.

---

## Handler Completeness

Rules that flag missing or misplaced write, read, and reaction paths.

### UNHANDLED_EVENT { #unhandled-event }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `warning` |

**Why.** An event with no registered handler is published but never consumed, so
a state change goes unobserved.

**Fix.** Register an event handler, projector, or process manager for this event,
or mark it `published=True` if it is intentionally external.

### UNRAISED_EVENT { #unraised-event }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `info` |

**Why.** An event that no aggregate or entity method raises is declared and
wired but produced by none of them. The check reads only aggregate and entity
method bodies, so an event raised from a command handler, subscriber, or
module-level factory is outside its scope and still shows here.

**Fix.** Raise the event from the aggregate or entity method that makes the
change it records, or remove the event if nothing produces it.

This is an advisory. It correlates a raise to a construction inside one method,
so an event raised through a helper (`self._emit(Placed(...))` calling
`self.raise_(e)`) or from caller code such as a command handler or subscriber is
still reported. Suppress the code where a documented pattern raises the event
outside an aggregate or entity method.

### UNUSED_COMMAND { #unused-command }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `warning` |

**Why.** A command with no handler cannot be processed, so the intent it
represents can never be fulfilled.

**Fix.** Add a command handler method for this command, or remove the command if
it is unused.

### ES_EVENT_MISSING_APPLY { #es-event-missing-apply }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `warning` |

**Why.** An event-sourced aggregate rebuilds its state by applying events; an
event without an `@apply` handler is never folded into state.

**Fix.** Add an `@apply` method on the aggregate for this event.

### PUBLISHED_NO_EXTERNAL_BROKER { #published-no-external-broker }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `warning` |

**Why.** Events marked `published` are meant to leave the bounded context, but
with no external broker configured they are only dispatched internally.

**Fix.** Configure `outbox.external_brokers`, or remove `published=True` if the
events are internal.

### AGGREGATE_WITHOUT_COMMAND_HANDLER { #aggregate-without-command-handler }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `warning` |

**Why.** An aggregate with no command handler has no write path, nothing can
change its state.

**Fix.** Add a command handler for the aggregate, or model it as a read-only
projection if no writes are expected.

### PROJECTION_WITHOUT_PROJECTOR { #projection-without-projector }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `warning` |

**Why.** A projection with no projector is never populated, so queries against it
will always return empty.

**Fix.** Add a projector for the projection, or set `externally_populated=True`
if it is filled by a subscriber.

### UNSOURCED_PROJECTION_FIELD { #unsourced-projection-field }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `info` |

**Why.** A projection field that no projector method writes is a dead column: it
renders in the read model and carries a type, but nothing ever fills it. The
check reads what a projection's projector methods write, either constructing the
projection with the field as a keyword or writing it as an attribute. A field
filled through a path the analysis cannot follow (a helper, a dict splat, a
`**kwargs` construction) is not reported, and the `identity_field` is exempt
because the framework fills it on write.

**Fix.** Write the field from the projector method that handles the event
carrying it, or drop the field from the projection if nothing sources it.

### QUERY_HANDLER_WITHOUT_QUERY { #query-handler-without-query }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `warning` |

**Why.** A projection with a query handler but no query has a read path that
nothing can invoke, no query is registered for the handler to serve.

**Fix.** Register a `Query(part_of=<projection>)` for the handler to serve, or
remove the query handler if the projection needs no read path.

### PROJECTOR_HANDLES_ORPHANED_EVENT { #projector-handles-orphaned-event }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `warning` |

**Why.** A projector handling an event the domain does not register is wired to a
type that can never be dispatched, usually a stale reference after a rename or
removal.

**Fix.** Register the event, or remove the handler for the orphaned type from the
projector.

### COMMAND_HANDLER_CROSS_CLUSTER { #command-handler-cross-cluster }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `warning` |

**Why.** A command handler that processes another cluster's command puts that
aggregate's write path outside its consistency boundary.

**Fix.** Move the command handler into the owning cluster, or model the
interaction as an event reaction across the boundary.

### EVENT_HANDLER_FOREIGN_EVENT { #event-handler-foreign-event }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `warning` |

**Why.** An event handler should react to events of its own aggregate cluster.
Handling another cluster's event couples two aggregates through the handler and
is often better expressed as a Process Manager coordinating the two.

**Fix.** Move the handler into the owning cluster, or introduce a
`ProcessManager` that reacts to the source event and issues a command into this
cluster.

### SUBSCRIBER_NO_STREAMS { #subscriber-no-streams }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `info` |

**Why.** A subscriber with no stream has nothing to consume, so it is registered
but can never be invoked.

**Fix.** Set the subscriber's `stream`, or remove the subscriber if it is unused.

### PROCESS_MANAGER_UNCLOSED { #process-manager-unclosed }

| | |
|---|---|
| **Category** | `handler_completeness` |
| **Level** | `info` |

**Why.** A process manager with no `end=True` handler never signals completion,
so its instances accumulate without being retired.

**Fix.** Mark the terminating handler with `end=True` so the process manager
closes its instances.

---

## Naming Conventions

Advisory rules that keep element names aligned with their role in the ubiquitous
language. All are `info`-level.

### EVENT_NOT_PAST_TENSE { #event-not-past-tense }

| | |
|---|---|
| **Category** | `naming_conventions` |
| **Level** | `info` |

**Why.** A domain event records a fact that has already happened, so a past-tense
name (`OrderPlaced`) reads truthfully; a gerund (`OrderPlacing`) describes an
in-flight action and reads like a command.

**Fix.** Rename the event to the past tense (e.g. `OrderPlaced`).

### COMMAND_NOT_IMPERATIVE { #command-not-imperative }

| | |
|---|---|
| **Category** | `naming_conventions` |
| **Level** | `info` |

**Why.** A command expresses an intent to act, so a verb-first imperative name
(`PlaceOrder`) reads truthfully; a noun-like name (`OrderCreation`) obscures the
intent.

**Fix.** Rename the command to a verb-first imperative phrase (e.g. `PlaceOrder`).

### AGGREGATE_NOT_NOUN { #aggregate-not-noun }

| | |
|---|---|
| **Category** | `naming_conventions` |
| **Level** | `info` |

**Why.** An aggregate models a thing in the domain, so a noun name (`Order`)
reads truthfully; a gerund, verb, or adjective (`OrderProcessing`) reads like a
process or capability rather than an entity.

**Fix.** Rename the aggregate to the domain-concept noun it represents (e.g.
`Order` rather than `OrderProcessing`).

---

## Persistence

### HANDLER_PERSISTS_AND_CALLS_OUT { #handler-persists-and-calls-out }

| | |
|---|---|
| **Category** | `persistence` |
| **Level** | `info` |

**Why.** A handler method runs inside a Unit of Work, and the transaction opens
at its first repository access. An external call after that point holds row locks
and a pooled connection for as long as the call takes, and a retry re-runs the
whole method and re-issues the call.

**Fix.** Split the method: one that persists, and one that calls out. A method
that touches no repository runs no transaction, so the call costs only
wall-clock time. When the call must follow the write, have the persisting method
raise an event and handle that.

This one is advisory rather than a warning, because a handler that needs the
call's result to compute its write is expected to do both in one method. Pass
the remote system's idempotency key so a retry does not duplicate the effect,
and silence the check on that handler with `suppress_checks`.

Process managers are covered too: their dispatch loop wraps each method in its
own Unit of Work, so the hazard is the same. The remedy differs, though. Every
process-manager method drives a state transition, and the transition is persisted
after each one, so splitting a method in two records two transitions where you
wanted one. Have the process manager raise an event and let a plain handler make
the call instead.

The rule is import-driven: it fires only when both signals resolve, a
`repository_for(...)` call and a call into a known I/O library, with the call
after the first `repository_for` in the same method. The `repo.get(...)` and
`repo.add(...)` that follow a `repository_for` do not resolve and are never
guessed at.

It reads one method body at a time and reports nothing it cannot see
statically, so it trades completeness for no false positives. A persist
delegated to a helper the method calls, a repository held on `self`, a persist
through the event store rather than `repository_for`, or an I/O client reached
through a local variable or a subscript are not flagged. A clean report is not
proof; when in doubt, keep the external call out of any method that also
persists. See
[ADR-0031](https://github.com/proteanhq/protean/blob/main/docs/adr/0031-handlers-persist-or-call-out.md).

### UNBOUNDED_INDEXED_STRING { #unbounded-indexed-string }

| | |
|---|---|
| **Category** | `persistence` |
| **Level** | `warning` |

**Why.** An index over an unbounded string field is unportable: the DDL fails on
SQL Server, needs a prefix length on MySQL, and is inefficient on PostgreSQL.

**Fix.** Give the field a bounded length (`String(max_length=N)`) sized to its
domain, or remove it from the index if it does not need to be indexed.

See the [UNBOUNDED_INDEXED_STRING reference](../concepts/protean-check/rules/unbounded-indexed-string.md)
for the exact scope, limits, and per-engine behaviour.

### UNINDEXED_FILTER_PATH { #unindexed-filter-path }

| | |
|---|---|
| **Category** | `persistence` |
| **Level** | `warning` |

**Why.** A repository filter on a field with no covering index forces a full
table scan on a relational backend. The cost is invisible on small development
data and grows with the production table.

**Fix.** Add an index led by this field to the aggregate
(`indexes=[Index("field")]`), or suppress the check when the table is small or
the query is a one-off, such as admin or reporting access.

A field counts as covered when it is the aggregate's identifier, carries a
single-column `unique` constraint, or leads a declared index. Target resolution
is conservative: a receiver the builder cannot resolve to an aggregate is
skipped rather than guessed, so an unresolved query is a silent miss instead of
a false positive.

See the [UNINDEXED_FILTER_PATH reference](../concepts/protean-check/rules/unindexed-filter-path.md)
for the recognized query surfaces and the resolution rules.

### LOW_POOL_SIZE { #low-pool-size }

| | |
|---|---|
| **Category** | `persistence` |
| **Level** | `warning` |

Fires when a database provider declares `pool_size` below `5`. The `memory`
provider is skipped, since it holds no connections.

**Why.** A connection pool smaller than the production default starves
concurrent requests under load, so operations queue or fail while waiting for a
free connection.

**Fix.** Raise the provider's `pool_size` to at least `5` for production
workloads.

---

## Versioning

### UPCASTER_GAP { #upcaster-gap }

| | |
|---|---|
| **Category** | `versioning` |
| **Level** | `warning` |

**Why.** Stored payloads at older versions with no upcaster path to the current
version fail to deserialize at read time.

**Fix.** Add upcasters covering the missing source versions. See
[Evolving Events Over Time](../guides/evolving-events.md).

---

## Deprecation

Rules that surface elements, fields, and options scheduled for removal. See the
[v0.17 migration guide](migration/v0-17.md) for the deprecation timeline.

!!! note "Deprecation coverage is a release gate"

    Every active framework-API deprecation is recorded in the declarative
    registry in `protean._deprecation` (`DEPRECATIONS`). Each framework-API warn
    site routes through `warn_from_registry` / `deprecated_from_registry`, which
    read the removal version and replacement advice from the entry. So a
    framework deprecation cannot warn without being registered, and a
    source-scan test fails if any module reaches for the low-level
    `warn_deprecated` / `@deprecated` primitives directly (the one exception is
    a user-declared deprecated *event*, whose removal comes from the user's
    event meta, not the registry). A deprecation may not ship unless it is both
    registered **and** covered by its detection mechanism: either a `protean
    check` rule that fires on it (`detection="check"`, with a `detection_hint`
    token that proves the rule fired), or, for an imperative call with no
    static site, its per-version `DeprecationWarning` plus a recorded `reason`
    for why `check` cannot see it (`detection="runtime"`). The audit in
    `tests/ir/test_deprecation_coverage_audit.py` enforces both arms.

### DEPRECATED_ELEMENT { #deprecated-element }

| | |
|---|---|
| **Category** | `deprecation` |
| **Level** | `info` |

**Why.** A deprecated element is scheduled for removal; code depending on it will
break at the removal version.

**Fix.** Migrate to the replacement element before the scheduled removal version.

### DEPRECATED_FIELD { #deprecated-field }

| | |
|---|---|
| **Category** | `deprecation` |
| **Level** | `info` |

**Why.** A deprecated field is scheduled for removal; code depending on it will
break at the removal version.

**Fix.** Migrate to the replacement field before the scheduled removal version.

### DEPRECATED_OPTION { #deprecated-option }

| | |
|---|---|
| **Category** | `deprecation` |
| **Level** | `warning` or `info` |

Emitted at `warning` level for a deprecated option alias (for example the
`event_sourced` alias), and at `info` level for a deprecated element option.

**Why.** The option is a deprecated alias scheduled for removal.

**Fix.** Use the current option name instead of the deprecated alias.

### DEPRECATED_EMAIL { #deprecated-email }

| | |
|---|---|
| **Category** | `deprecation` |
| **Level** | `info` |

**Why.** The email subsystem is deprecated and scheduled for removal in v1.0.0.

**Fix.** Notify from an event handler or subscriber that calls an
application-level notification service instead.

### DEPRECATED_CONFIG { #deprecated-config }

| | |
|---|---|
| **Category** | `deprecation` |
| **Level** | `info` |

**Why.** A non-default `email_providers` config block uses the deprecated email
subsystem, scheduled for removal in v1.0.0. The default block stays silent.

**Fix.** Notify from an event handler or subscriber that calls an
application-level notification service instead.

### DEPRECATED_IMPORT { #deprecated-import }

| | |
|---|---|
| **Category** | `deprecation` |
| **Level** | `info` |

Detected by an on-disk scan of each registered element's source module: a
`Method` / `Nested` serializer-field call site, or a deprecated `protean.utils.*`
plumbing name (imported by name or reached through a `protean.utils` attribute
access). All are scheduled for removal in v1.0.0. The diagnostic is attributed to
the module and emitted once per deprecated symbol, not once per element in it.

**Scope.** The scan only reads modules that host a registered element (the same
element-oriented boundary as the infra-import scan). A deprecated use in a
plain helper module or the domain composition root (one with no registered
class) is not seen; the per-declaration `DeprecationWarning` still fires there
at runtime.

**Why.** A deprecated import surface is scheduled for removal; code using it will
break at the removal version.

**Fix.** Remove the deprecated serializer field, or stop importing the internal
`protean.utils` plumbing name.

---

## Custom rules

Rules loaded through `[lint].rules` emit findings under the `custom` category by
default. See
[Writing custom rules](../guides/architecture-fitness-functions.md#writing-custom-rules).
