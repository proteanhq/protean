"""Typed diagnostics and the stable diagnostic-code registry.

This module is the single source of truth for every rule-based diagnostic
code Protean emits from IR build, ``protean check``, and validation warnings.
Each code is a stable public identifier: renaming or removing one is a
breaking change, guarded by the golden code-set snapshot test. Producers
(``ir.builder``, ``domain.validation``, ``_deprecation``) reference
:class:`DiagnosticCode` members instead of bare string literals, and build
their wire records through :func:`build_diagnostic`, so the code string and
its metadata live here once and nowhere else.

Out of scope: the ``_errors`` channel emits a diagnostic whose ``code`` is
the raised exception's class name (``domain.validation``), not a rule code.
Those dynamic codes are computed, not registered here, and the no-bare-literal
linter does not flag them.

The wire shape is unchanged: :func:`build_diagnostic` returns a plain
``dict`` with exactly the keys the IR JSON, SARIF, and ``check`` output
already carry. :class:`Diagnostic` names that shape for type-checking.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict


class DiagnosticCode(StrEnum):
    """Stable identifier for every diagnostic Protean can emit.

    A ``StrEnum`` so a member serializes to its plain code string in JSON and
    compares equal to that string, while call sites reference the member (never
    a bare literal).
    """

    ADAPTER_CALL_IN_DOMAIN = "ADAPTER_CALL_IN_DOMAIN"
    AGGREGATE_NOT_NOUN = "AGGREGATE_NOT_NOUN"
    AGGREGATE_NO_INVARIANTS = "AGGREGATE_NO_INVARIANTS"
    AGGREGATE_TOO_LARGE = "AGGREGATE_TOO_LARGE"
    AGGREGATE_WITHOUT_COMMAND_HANDLER = "AGGREGATE_WITHOUT_COMMAND_HANDLER"
    CIRCULAR_CLUSTER_DEPENDENCY = "CIRCULAR_CLUSTER_DEPENDENCY"
    COMMAND_HANDLER_CROSS_CLUSTER = "COMMAND_HANDLER_CROSS_CLUSTER"
    COMMAND_NOT_IMPERATIVE = "COMMAND_NOT_IMPERATIVE"
    CROSS_AGGREGATE_REFERENCE = "CROSS_AGGREGATE_REFERENCE"
    DEPRECATED_CONFIG = "DEPRECATED_CONFIG"
    DEPRECATED_ELEMENT = "DEPRECATED_ELEMENT"
    DEPRECATED_EMAIL = "DEPRECATED_EMAIL"
    DEPRECATED_FIELD = "DEPRECATED_FIELD"
    DEPRECATED_IMPORT = "DEPRECATED_IMPORT"
    DEPRECATED_OPTION = "DEPRECATED_OPTION"
    ES_AGGREGATE_NO_EVENTS = "ES_AGGREGATE_NO_EVENTS"
    ES_EVENT_MISSING_APPLY = "ES_EVENT_MISSING_APPLY"
    EVENT_HANDLER_FOREIGN_EVENT = "EVENT_HANDLER_FOREIGN_EVENT"
    EVENT_NOT_PAST_TENSE = "EVENT_NOT_PAST_TENSE"
    EVENT_WITHOUT_DATA = "EVENT_WITHOUT_DATA"
    HANDLER_TOO_BROAD = "HANDLER_TOO_BROAD"
    INFRA_IMPORT_IN_DOMAIN = "INFRA_IMPORT_IN_DOMAIN"
    LOW_POOL_SIZE = "LOW_POOL_SIZE"
    PROCESS_MANAGER_UNCLOSED = "PROCESS_MANAGER_UNCLOSED"
    PROJECTION_WITHOUT_PROJECTOR = "PROJECTION_WITHOUT_PROJECTOR"
    PROJECTOR_HANDLES_ORPHANED_EVENT = "PROJECTOR_HANDLES_ORPHANED_EVENT"
    PUBLISHED_NO_EXTERNAL_BROKER = "PUBLISHED_NO_EXTERNAL_BROKER"
    QUERY_HANDLER_WITHOUT_QUERY = "QUERY_HANDLER_WITHOUT_QUERY"
    SUBSCRIBER_NO_STREAMS = "SUBSCRIBER_NO_STREAMS"
    UNBOUNDED_INDEXED_STRING = "UNBOUNDED_INDEXED_STRING"
    UNHANDLED_EVENT = "UNHANDLED_EVENT"
    UNINDEXED_FILTER_PATH = "UNINDEXED_FILTER_PATH"
    UNUSED_COMMAND = "UNUSED_COMMAND"
    UPCASTER_GAP = "UPCASTER_GAP"
    VALUE_OBJECT_MUTABLE_FIELD = "VALUE_OBJECT_MUTABLE_FIELD"


class DiagnosticRule(TypedDict):
    """The ``rule`` block carried on a diagnostic: why it fires and how to fix it."""

    rationale: str
    fix: str


class _DiagnosticRequired(TypedDict):
    code: str
    category: str
    element: str
    level: str
    message: str
    rule: DiagnosticRule
    suggestion: str


class Diagnostic(_DiagnosticRequired, total=False):
    """The wire shape of a single ``_diagnostics`` record.

    ``field`` is present only on field-scoped diagnostics; every other key is
    always present. Field order is irrelevant — the IR, SARIF, and ``check``
    serializers all emit with ``sort_keys=True``.
    """

    field: str


@dataclass(frozen=True)
class CodeMeta:
    """Metadata for one diagnostic code, resolved by code and never repeated
    on an instance.

    ``category`` and ``rationale`` are constant per code. ``level`` and
    ``fix`` are the canonical defaults; a producer may override either at an
    emission site (e.g. a code emitted at two severities, or a fix built from
    per-instance context). ``meaning`` is a one-line human summary.
    """

    category: str
    level: str
    meaning: str
    rationale: str
    fix: str


REGISTRY: dict[DiagnosticCode, CodeMeta] = {
    DiagnosticCode.ADAPTER_CALL_IN_DOMAIN: CodeMeta(
        category="bounded_context",
        level="warning",
        meaning="A domain element's method calls a concrete infrastructure adapter.",
        rationale=(
            "Domain elements must not depend on concrete infrastructure "
            "adapters; calling into `protean.adapters` from a domain method "
            "couples the domain layer to a specific adapter at runtime and "
            "breaks the ports-and-adapters boundary."
        ),
        fix=(
            "Remove the `protean.adapters` call from the domain method. Depend "
            "on domain-layer abstractions and let the adapter be wired through "
            "the domain's provider configuration instead."
        ),
    ),
    DiagnosticCode.AGGREGATE_NOT_NOUN: CodeMeta(
        category="naming_conventions",
        level="info",
        meaning="An aggregate is not named as a noun.",
        rationale=(
            "An aggregate models a thing in the domain, so a noun name "
            "(`Order`) reads truthfully; a gerund, verb, or adjective "
            "(`OrderProcessing`) reads like a process or capability rather "
            "than an entity."
        ),
        fix=(
            "Rename the aggregate to the domain-concept noun it represents "
            "(e.g. `Order` rather than `OrderProcessing`)."
        ),
    ),
    DiagnosticCode.AGGREGATE_NO_INVARIANTS: CodeMeta(
        category="aggregate_design",
        level="info",
        meaning="An aggregate declares no invariants.",
        rationale=(
            "An aggregate is a consistency boundary. With no pre- or "
            "post-invariants it enforces no business rules and is usually an "
            "anemic data holder rather than a true aggregate."
        ),
        fix=(
            "Add one or more `@invariant.pre` or `@invariant.post` methods "
            "expressing the business rules the aggregate must always satisfy, "
            "or reconsider whether this concept is an aggregate at all."
        ),
    ),
    DiagnosticCode.AGGREGATE_TOO_LARGE: CodeMeta(
        category="aggregate_design",
        level="info",
        meaning="An aggregate has more fields than the configured size limit.",
        rationale=(
            "A large aggregate is a consistency boundary and contention "
            "hotspot; oversized clusters are hard to keep transactionally "
            "consistent."
        ),
        fix=(
            "Split the aggregate into smaller aggregates, or raise `[lint] "
            "aggregate_size_limit` if the size is intentional."
        ),
    ),
    DiagnosticCode.AGGREGATE_WITHOUT_COMMAND_HANDLER: CodeMeta(
        category="handler_completeness",
        level="warning",
        meaning="An aggregate has no command handler, so no write path.",
        rationale=(
            "An aggregate with no command handler has no write path \u2014 nothing "
            "can change its state."
        ),
        fix=(
            "Add a command handler for the aggregate, or model it as a "
            "read-only projection if no writes are expected."
        ),
    ),
    DiagnosticCode.CIRCULAR_CLUSTER_DEPENDENCY: CodeMeta(
        category="bounded_context",
        level="warning",
        meaning="Aggregate clusters reference each other in a cycle.",
        rationale=(
            "Circular identity references between aggregate clusters prevent "
            "independent decomposition, deployment, and event sourcing of the "
            "aggregates."
        ),
        fix=(
            "Break the cycle by replacing one direction of the reference with "
            "a domain event or a process manager that coordinates the two "
            "aggregates asynchronously."
        ),
    ),
    DiagnosticCode.COMMAND_HANDLER_CROSS_CLUSTER: CodeMeta(
        category="handler_completeness",
        level="warning",
        meaning="A command handler processes another cluster's command.",
        rationale=(
            "A command handler that processes another cluster's command puts "
            "that aggregate's write path outside its consistency boundary."
        ),
        fix=(
            "Move the command handler into the owning cluster, or model the "
            "interaction as an event reaction across the boundary."
        ),
    ),
    DiagnosticCode.COMMAND_NOT_IMPERATIVE: CodeMeta(
        category="naming_conventions",
        level="info",
        meaning="A command is not named in the imperative mood.",
        rationale=(
            "A command expresses an intent to act, so a verb-first imperative "
            "name (`PlaceOrder`) reads truthfully; a noun-like name "
            "(`OrderCreation`) obscures the intent."
        ),
        fix=(
            "Rename the command to a verb-first imperative phrase (e.g. `PlaceOrder`)."
        ),
    ),
    DiagnosticCode.CROSS_AGGREGATE_REFERENCE: CodeMeta(
        category="aggregate_design",
        level="warning",
        meaning="A field holds a direct reference to another aggregate root.",
        rationale=(
            "Aggregates coordinate other aggregates by identity, not by object "
            "reference (Vernon's Rule 3). A `Reference` to another aggregate's "
            "root couples the two into one object graph and invites a single "
            "transaction to span both clusters. The compliant reference is a "
            "child entity pointing back at its own aggregate root, where the "
            "target is the element's own cluster."
        ),
        fix=(
            "Hold the other aggregate by its identifier instead of a "
            "`Reference`. Replace `Reference(<Other>)` with an `Identifier` "
            "field (for example `<other>_id: Identifier()`) and load the other "
            "aggregate through its own repository when needed."
        ),
    ),
    DiagnosticCode.DEPRECATED_CONFIG: CodeMeta(
        category="deprecation",
        level="info",
        meaning="A configuration block uses a deprecated subsystem.",
        rationale=(
            "The email subsystem is deprecated and scheduled for removal in v1.0.0."
        ),
        fix=(
            "Migrate off the deprecated configuration block before the "
            "scheduled removal version."
        ),
    ),
    DiagnosticCode.DEPRECATED_ELEMENT: CodeMeta(
        category="deprecation",
        level="info",
        meaning="A registered element is deprecated.",
        rationale=(
            "A deprecated element is scheduled for removal; code depending on "
            "it will break at the removal version."
        ),
        fix=(
            "Migrate to the replacement element before the scheduled removal version."
        ),
    ),
    DiagnosticCode.DEPRECATED_EMAIL: CodeMeta(
        category="deprecation",
        level="info",
        meaning="An element uses the deprecated email subsystem.",
        rationale=(
            "The email subsystem is deprecated and scheduled for removal in v1.0.0."
        ),
        fix=(
            "Notify from an event handler or subscriber that calls an "
            "application-level notification service instead."
        ),
    ),
    DiagnosticCode.DEPRECATED_FIELD: CodeMeta(
        category="deprecation",
        level="info",
        meaning="A field is deprecated or uses a deprecated argument.",
        rationale=(
            "A deprecated field is scheduled for removal; code reading or "
            "writing it will break at the removal version."
        ),
        fix=("Migrate to the replacement field before the scheduled removal version."),
    ),
    DiagnosticCode.DEPRECATED_IMPORT: CodeMeta(
        category="deprecation",
        level="info",
        meaning="A module imports a deprecated surface.",
        rationale=(
            "A deprecated import surface is scheduled for removal; code using "
            "it will break at the removal version."
        ),
        fix=(
            "Stop using the deprecated import surface before the scheduled "
            "removal version."
        ),
    ),
    DiagnosticCode.DEPRECATED_OPTION: CodeMeta(
        category="deprecation",
        level="info",
        meaning="An element uses a deprecated decorator or register option.",
        rationale="The option is a deprecated alias scheduled for removal.",
        fix="Use `event_sourced` instead of the deprecated alias.",
    ),
    DiagnosticCode.ES_AGGREGATE_NO_EVENTS: CodeMeta(
        category="aggregate_design",
        level="warning",
        meaning="An event-sourced aggregate registers no events.",
        rationale=(
            "An event-sourced aggregate reconstitutes its state by replaying "
            "its events. With no events registered it can record no state "
            "changes and cannot be rebuilt from its stream."
        ),
        fix=(
            "Declare at least one domain event with `part_of=<Aggregate>` and "
            "raise it from the aggregate's behaviour, or drop "
            "`event_sourced=True` if the aggregate is not meant to be "
            "event-sourced."
        ),
    ),
    DiagnosticCode.ES_EVENT_MISSING_APPLY: CodeMeta(
        category="handler_completeness",
        level="warning",
        meaning="An event on an event-sourced aggregate has no @apply handler.",
        rationale=(
            "An event-sourced aggregate rebuilds its state by applying events; "
            "an event without an @apply handler is never folded into state."
        ),
        fix="Add an @apply method on the aggregate for this event.",
    ),
    DiagnosticCode.EVENT_HANDLER_FOREIGN_EVENT: CodeMeta(
        category="handler_completeness",
        level="warning",
        meaning="An event handler reacts to another cluster's event.",
        rationale=(
            "An event handler should react to events of its own aggregate "
            "cluster. Handling another cluster's event couples two aggregates "
            "through the handler and is often better expressed as a Process "
            "Manager coordinating the two."
        ),
        fix=(
            "Move the handler into the owning cluster, or introduce a "
            "ProcessManager that reacts to the source event and issues a "
            "command into this cluster."
        ),
    ),
    DiagnosticCode.EVENT_NOT_PAST_TENSE: CodeMeta(
        category="naming_conventions",
        level="info",
        meaning="An event is not named in the past tense.",
        rationale=(
            "A domain event records a fact that has already happened, so a "
            "past-tense name (`OrderPlaced`) reads truthfully; a gerund "
            "(`OrderPlacing`) describes an in-flight action and reads like a "
            "command."
        ),
        fix="Rename the event to the past tense (e.g. `OrderPlaced`).",
    ),
    DiagnosticCode.EVENT_WITHOUT_DATA: CodeMeta(
        category="aggregate_design",
        level="info",
        meaning="An event declares no fields.",
        rationale=(
            "An event with no fields carries no information beyond its name, "
            "so consumers cannot react to what actually changed."
        ),
        fix=(
            "Add fields capturing the state change, or confirm the event is "
            "intentionally a bare signal."
        ),
    ),
    DiagnosticCode.HANDLER_TOO_BROAD: CodeMeta(
        category="aggregate_design",
        level="info",
        meaning="A handler handles more message types than the breadth limit.",
        rationale=(
            "A handler that handles many message types accretes unrelated "
            "responsibilities and becomes hard to reason about."
        ),
        fix=(
            "Split the handler into focused handlers, or raise `[lint] "
            "handler_breadth_limit` if the breadth is intentional."
        ),
    ),
    DiagnosticCode.INFRA_IMPORT_IN_DOMAIN: CodeMeta(
        category="bounded_context",
        level="warning",
        meaning="A domain module imports from protean.adapters.",
        rationale=(
            "Domain elements must not depend on concrete infrastructure "
            "adapters; importing from `protean.adapters` couples the domain "
            "layer to a specific adapter and breaks the ports-and-adapters "
            "boundary."
        ),
        fix=(
            "Remove the `protean.adapters` import from the domain module. "
            "Depend on domain-layer abstractions and let the adapter be wired "
            "through the domain's provider configuration instead."
        ),
    ),
    DiagnosticCode.LOW_POOL_SIZE: CodeMeta(
        category="persistence",
        level="warning",
        meaning="A database provider's pool_size is below the production default.",
        rationale=(
            "A connection pool smaller than the production default starves "
            "concurrent requests under load, so operations queue or fail while "
            "waiting for a free connection."
        ),
        fix=(
            "Raise the provider's `pool_size` to at least the production "
            "default for production workloads."
        ),
    ),
    DiagnosticCode.PROCESS_MANAGER_UNCLOSED: CodeMeta(
        category="handler_completeness",
        level="info",
        meaning="A process manager has no end=True handler to close instances.",
        rationale=(
            "A process manager with no `end=True` handler never signals "
            "completion, so its instances accumulate without being retired."
        ),
        fix=(
            "Mark the terminating handler with `end=True` so the process "
            "manager closes its instances."
        ),
    ),
    DiagnosticCode.PROJECTION_WITHOUT_PROJECTOR: CodeMeta(
        category="handler_completeness",
        level="warning",
        meaning="A projection has no projector to populate it.",
        rationale=(
            "A projection with no projector is never populated, so queries "
            "against it will always return empty."
        ),
        fix=(
            "Add a projector for the projection, or set "
            "`externally_populated=True` if it is filled by a subscriber."
        ),
    ),
    DiagnosticCode.PROJECTOR_HANDLES_ORPHANED_EVENT: CodeMeta(
        category="handler_completeness",
        level="warning",
        meaning="A projector handles an event the domain does not register.",
        rationale=(
            "A projector handling an event the domain does not register is "
            "wired to a type that can never be dispatched \u2014 usually a stale "
            "reference after a rename or removal."
        ),
        fix=(
            "Register the event, or remove the handler for the orphaned type "
            "from the projector."
        ),
    ),
    DiagnosticCode.PUBLISHED_NO_EXTERNAL_BROKER: CodeMeta(
        category="handler_completeness",
        level="warning",
        meaning="Published events exist but no external broker is configured.",
        rationale=(
            "Events marked published are meant to leave the bounded context, "
            "but with no external broker configured they are only dispatched "
            "internally."
        ),
        fix=(
            "Configure `outbox.external_brokers`, or remove `published=True` "
            "if the events are internal."
        ),
    ),
    DiagnosticCode.QUERY_HANDLER_WITHOUT_QUERY: CodeMeta(
        category="handler_completeness",
        level="warning",
        meaning="A projection has a query handler but no query to serve.",
        rationale=(
            "A projection with a query handler but no query has a read path "
            "that nothing can invoke \u2014 no query is registered for the handler "
            "to serve."
        ),
        fix=(
            "Register a `Query(part_of=<projection>)` for the handler to "
            "serve, or remove the query handler if the projection needs no "
            "read path."
        ),
    ),
    DiagnosticCode.SUBSCRIBER_NO_STREAMS: CodeMeta(
        category="handler_completeness",
        level="info",
        meaning="A subscriber declares no stream to consume.",
        rationale=(
            "A subscriber with no stream has nothing to consume, so it is "
            "registered but can never be invoked."
        ),
        fix=(
            "Set the subscriber's `stream`, or remove the subscriber if it is unused."
        ),
    ),
    DiagnosticCode.UNBOUNDED_INDEXED_STRING: CodeMeta(
        category="persistence",
        level="warning",
        meaning="An indexed String field has no max_length.",
        rationale=(
            "An index over an unbounded string field is unportable: the DDL "
            "fails on SQL Server, needs a prefix length on MySQL, and is "
            "inefficient on PostgreSQL."
        ),
        fix=(
            "Give the field a bounded length (`String(max_length=N)`) sized to "
            "its domain, or remove it from the index if it does not need to be "
            "indexed."
        ),
    ),
    DiagnosticCode.UNHANDLED_EVENT: CodeMeta(
        category="handler_completeness",
        level="warning",
        meaning="An event has no registered handler.",
        rationale=(
            "An event with no registered handler is published but never "
            "consumed, so a state change goes unobserved."
        ),
        fix=(
            "Register an event handler, projector, or process manager for this "
            "event, or mark it `published=True` if it is intentionally "
            "external."
        ),
    ),
    DiagnosticCode.UNINDEXED_FILTER_PATH: CodeMeta(
        category="persistence",
        level="warning",
        meaning="A repository filter path has no covering index.",
        rationale=(
            "A repository filter on a field with no covering index forces a "
            "full table scan on a relational backend. The cost is invisible on "
            "small development data and grows with the production table."
        ),
        fix=(
            "Add an index led by this field to the aggregate "
            '(`indexes=[Index("field")]`), or suppress the check when the '
            "table is small or the query is a one-off (admin/reporting)."
        ),
    ),
    DiagnosticCode.UNUSED_COMMAND: CodeMeta(
        category="handler_completeness",
        level="warning",
        meaning="A command has no registered handler.",
        rationale=(
            "A command with no handler cannot be processed, so the intent it "
            "represents can never be fulfilled."
        ),
        fix=(
            "Add a command handler method for this command, or remove the "
            "command if it is unused."
        ),
    ),
    DiagnosticCode.UPCASTER_GAP: CodeMeta(
        category="versioning",
        level="warning",
        meaning=("A stored event version has no upcaster path to the current version."),
        rationale=(
            "Stored payloads at older versions with no upcaster path to the "
            "current version fail to deserialize at read time."
        ),
        fix="Add upcasters covering the missing source versions.",
    ),
    DiagnosticCode.VALUE_OBJECT_MUTABLE_FIELD: CodeMeta(
        category="aggregate_design",
        level="warning",
        meaning="A value object has a mutable collection field.",
        rationale=(
            "Value objects are compared by value and must be immutable. A "
            "`List` or `Dict` field gives the value object mutable internal "
            "state, so two instances that should be equal can diverge and "
            "value equality no longer holds."
        ),
        fix=(
            "Replace the mutable collection with an immutable representation, "
            "or move the collection onto the containing entity or aggregate. "
            "If the values form a concept with its own identity, model them as "
            "an entity referenced by the aggregate instead."
        ),
    ),
}


def resolve(code: DiagnosticCode) -> CodeMeta:
    """Return the registry metadata for ``code``.

    The thin ``_warnings`` channel stores only ``code`` plus per-instance
    context; callers resolve category/level/rationale/fix through this.
    """
    return REGISTRY[code]


def build_diagnostic(
    code: DiagnosticCode,
    *,
    element: str,
    message: str,
    level: str | None = None,
    field: str | None = None,
    rationale: str | None = None,
    fix: str | None = None,
    suggestion: str | None = None,
) -> dict[str, Any]:
    """Build one ``_diagnostics`` wire record for ``code``.

    Resolves ``category``/``level``/``rationale``/``fix`` from the registry;
    pass ``level``/``rationale``/``fix`` to override the canonical default at
    a site that diverges. ``suggestion`` defaults to the resolved ``fix``.
    The returned dict carries exactly the wire keys (plus ``field`` when
    given) — the shape the IR, SARIF, and ``check`` output already emit.
    """
    meta = REGISTRY[code]
    resolved_rationale = rationale if rationale is not None else meta.rationale
    resolved_fix = fix if fix is not None else meta.fix
    diagnostic: dict[str, Any] = {
        "code": code.value,
        "category": meta.category,
        "element": element,
        "level": level if level is not None else meta.level,
        "message": message,
        "rule": {"rationale": resolved_rationale, "fix": resolved_fix},
        "suggestion": suggestion if suggestion is not None else resolved_fix,
    }
    if field is not None:
        diagnostic["field"] = field
    return diagnostic
