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
from typing import Literal, TypedDict


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
    CONFIG_AMBIGUOUS_ELEMENT_NAME = "CONFIG_AMBIGUOUS_ELEMENT_NAME"
    CONFIG_ELEMENT_NOT_REGISTERED = "CONFIG_ELEMENT_NOT_REGISTERED"
    CONFIG_EVENT_STORE_NOT_INITIALIZED = "CONFIG_EVENT_STORE_NOT_INITIALIZED"
    CONFIG_UNRESOLVED_ENV_VAR = "CONFIG_UNRESOLVED_ENV_VAR"
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
    HANDLER_PERSISTS_AND_CALLS_OUT = "HANDLER_PERSISTS_AND_CALLS_OUT"
    INFRA_IMPORT_IN_DOMAIN = "INFRA_IMPORT_IN_DOMAIN"
    INVARIANT_POST_FAILED = "INVARIANT_POST_FAILED"
    INVARIANT_PRE_FAILED = "INVARIANT_PRE_FAILED"
    IR_STALE = "IR_STALE"
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
    UNRAISED_EVENT = "UNRAISED_EVENT"
    UNSUPPORTED_ELEMENT_CLASS = "UNSUPPORTED_ELEMENT_CLASS"
    UNUSED_COMMAND = "UNUSED_COMMAND"
    UPCASTER_GAP = "UPCASTER_GAP"
    USAGE_CACHE_BACKED_NO_REPOSITORY = "USAGE_CACHE_BACKED_NO_REPOSITORY"
    USAGE_DUPLICATE_DATABASE_MODEL = "USAGE_DUPLICATE_DATABASE_MODEL"
    USAGE_ELEMENT_NOT_REGISTERED = "USAGE_ELEMENT_NOT_REGISTERED"
    USAGE_ENRICHER_NOT_CALLABLE = "USAGE_ENRICHER_NOT_CALLABLE"
    USAGE_NOT_A_PROJECTION = "USAGE_NOT_A_PROJECTION"
    USAGE_UNKNOWN_ELEMENT_TYPE = "USAGE_UNKNOWN_ELEMENT_TYPE"
    VALUE_OBJECT_INVARIANT_FAILED = "VALUE_OBJECT_INVARIANT_FAILED"
    VALUE_OBJECT_MUTABLE_FIELD = "VALUE_OBJECT_MUTABLE_FIELD"


class DiagnosticRule(TypedDict):
    """The ``rule`` block carried on a diagnostic: why it fires and how to fix it."""

    rationale: str
    fix: str


class ResolvingOperationDict(TypedDict):
    """The ``resolving_operation`` block on a diagnostic: the command that clears it.

    ``command`` is the console script to run and ``args`` its fixed arguments:
    the structured form an agent dispatches directly. ``display`` is the same
    command rendered as one string for a human to read. ``display`` is for
    reading, not shell-safe quoting.
    """

    command: str
    args: list[str]
    display: str


class _DiagnosticRequired(TypedDict):
    code: str
    category: str
    element: str
    level: str
    message: str
    rule: DiagnosticRule
    suggestion: str


class Diagnostic(_DiagnosticRequired, total=False):
    """The wire shape of a diagnostic built by :func:`build_diagnostic`.

    ``field`` is present only on field-scoped diagnostics. ``location`` is
    provisioned on the wire shape but no core IR/``protean check`` producer sets
    it today; it is currently carried on the exception attribute path
    (``ProteanException.location``), not on any IR/``check`` diagnostic.
    ``resolving_operation`` is present only for a code whose failure a
    deterministic ``protean`` command clears (the registry holds the mapping);
    a code with no such command omits the key. Every other key is always
    present on diagnostics built through :func:`build_diagnostic`.
    This does not describe every entry in ``ir["diagnostics"]``: custom lint
    rules (``ir.builder._run_custom_lint_rules``) contribute dicts that only
    require ``code``/``element``/``level``/``message``, with ``rule`` and
    ``suggestion`` left optional. Field order is irrelevant — the IR, SARIF,
    and ``check`` serializers all emit with ``sort_keys=True``.
    """

    field: str
    location: str
    resolving_operation: ResolvingOperationDict


@dataclass(frozen=True)
class ResolvingOperation:
    """A deterministic command that clears a diagnostic.

    ``command`` is the console script an agent invokes (e.g.
    ``"protean-check-staleness"``); ``args`` are the fixed arguments that make it
    resolve the failure (e.g. ``("--fix",)``). An agent runs ``command`` with
    ``args`` directly, supplying its own context (``--domain``, ``--dir``); a
    human reads :meth:`render`.
    """

    command: str
    args: tuple[str, ...] = ()

    def render(self) -> str:
        """The command as a human would read it: ``command`` and ``args`` joined
        by spaces. For display only, not shell-quoted."""
        return " ".join((self.command, *self.args))

    def as_wire(self) -> ResolvingOperationDict:
        """The wire record: structured ``command``/``args`` plus the rendered
        ``display`` string."""
        return {
            "command": self.command,
            "args": list(self.args),
            "display": self.render(),
        }


@dataclass(frozen=True)
class CodeMeta:
    """Metadata for one diagnostic code, resolved by code and never repeated
    on an instance.

    ``category`` is constant per code. ``level``, ``rationale``, and ``fix``
    are the canonical defaults; a producer may override any of them at an
    emission site (e.g. a code emitted at two severities, or a rationale/fix
    built from per-instance context, as ``DEPRECATED_FIELD``'s `pickled=`
    diagnostic and ``DEPRECATED_OPTION`` do). ``meaning`` is a one-line human
    summary.

    ``kind`` says how the code reaches a user: ``"lint"`` for a static rule
    surfaced by ``protean check`` over the IR, ``"raise"`` for a code carried on
    an exception raised at init or runtime, ``"staleness"`` for a code produced
    by :func:`~protean.ir.staleness.staleness_diagnostic` from a
    ``StalenessResult``. Most ``"raise"`` codes describe runtime accessor misuse
    that static analysis cannot see, so they stay off the ``protean check``
    catalog; a few could later grow a lint rule that emits the same code at
    design time.

    ``resolution`` names the deterministic command that clears the failure, when
    one exists; :func:`build_diagnostic` renders it onto the wire as
    ``resolving_operation``. Most codes have no such command and leave it
    ``None``, so the fix stays prose. The code to command map lives in one place,
    here in the registry. ``kind`` and ``resolution`` are independent: a lint
    code could grow a resolution, and a staleness code need not have one.
    """

    category: str
    level: str
    meaning: str
    rationale: str
    fix: str
    kind: Literal["lint", "raise", "staleness"] = "lint"
    resolution: ResolvingOperation | None = None


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
    DiagnosticCode.CONFIG_AMBIGUOUS_ELEMENT_NAME: CodeMeta(
        category="configuration",
        level="error",
        kind="raise",
        meaning="A short element name matches more than one registered element.",
        rationale=(
            "A short element name that matches more than one registered element "
            "cannot be resolved to a single element, so the lookup is ambiguous."
        ),
        fix=(
            "Look the element up by its fully qualified name to disambiguate, or "
            "rename one of the colliding elements."
        ),
    ),
    DiagnosticCode.CONFIG_ELEMENT_NOT_REGISTERED: CodeMeta(
        category="configuration",
        level="error",
        kind="raise",
        meaning="A lookup names an element the domain has not registered.",
        rationale=(
            "Resolving an element by name requires it to be registered with the "
            "domain; an unregistered name has nothing to resolve to."
        ),
        fix=(
            "Register the element with the domain before it is looked up, or "
            "correct the name to one that is registered."
        ),
    ),
    DiagnosticCode.CONFIG_EVENT_STORE_NOT_INITIALIZED: CodeMeta(
        category="configuration",
        level="error",
        kind="raise",
        meaning="The event store is used before the domain is initialized.",
        rationale=(
            "The event store is wired during `domain.init()`; using it before "
            "then leaves the store unset."
        ),
        fix="Call `domain.init()` before using the event store.",
    ),
    DiagnosticCode.CONFIG_UNRESOLVED_ENV_VAR: CodeMeta(
        category="configuration",
        level="error",
        kind="raise",
        meaning="A `${VAR}` reference in configuration resolves to no value.",
        rationale=(
            "A `${VAR}` placeholder in configuration is substituted from the "
            "environment at load time; with the variable unset and no default "
            "given, it resolves to nothing."
        ),
        fix=(
            "Set the environment variable in the runtime environment, or give "
            "the placeholder a default with `${VAR|default}`."
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
    DiagnosticCode.HANDLER_PERSISTS_AND_CALLS_OUT: CodeMeta(
        category="persistence",
        level="info",
        meaning=(
            "A handler method both persists through a repository and calls an "
            "external system."
        ),
        rationale=(
            "A handler method runs inside a Unit of Work, and the transaction "
            "opens at the first repository access. An external call after that "
            "point holds row locks and a pooled connection for as long as the "
            "call takes, and a retry re-runs the whole method, re-issuing the "
            "call (ADR-0031)."
        ),
        fix=(
            "Split the method: one that persists, and one that calls out. When "
            "the call must follow the write, have the persisting method raise "
            "an event and handle that. On a process manager, prefer raising an "
            "event for a plain handler to act on, because splitting a "
            "transition in two records two transitions where you wanted one. "
            "When the method genuinely needs the call's result to compute its "
            "write, keep both and pass the remote system's idempotency key so a "
            "retry does not duplicate the effect."
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
    DiagnosticCode.INVARIANT_POST_FAILED: CodeMeta(
        category="invariants",
        level="error",
        kind="raise",
        meaning=(
            "A post-condition invariant on an aggregate, entity, or domain "
            "service did not hold."
        ),
        rationale=(
            "An `@invariant.post` states a condition that must hold once an "
            "aggregate, entity, or domain service is built, changed, or run; the "
            "resulting state broke that condition."
        ),
        fix=(
            "Correct the state so the post-condition holds, or catch the "
            "`ValidationError`. The error messages name what failed."
        ),
    ),
    DiagnosticCode.INVARIANT_PRE_FAILED: CodeMeta(
        category="invariants",
        level="error",
        kind="raise",
        meaning=(
            "A pre-condition invariant on an aggregate, entity, or domain "
            "service did not hold."
        ),
        rationale=(
            "An `@invariant.pre` guards the state required before an aggregate, "
            "entity, or domain service is changed or run; the change was "
            "attempted while that guard did not hold."
        ),
        fix=(
            "Satisfy the pre-condition first, or catch the `ValidationError` and "
            "correct the input. The error messages name what failed."
        ),
    ),
    DiagnosticCode.IR_STALE: CodeMeta(
        category="versioning",
        level="warning",
        kind="staleness",
        meaning="The materialized IR baseline is out of date with the live domain.",
        rationale=(
            "The materialized `.protean/ir.json` baseline no longer matches the "
            "live domain's checksum, so anything reading the baseline (a "
            "compatibility diff, or an agent inspecting the contract) sees a "
            "stale view of the domain."
        ),
        fix=(
            "Regenerate the baseline with `protean-check-staleness --fix` (or "
            "`protean ir show --domain <domain> --canonical`) and commit the "
            "updated file."
        ),
        resolution=ResolvingOperation("protean-check-staleness", ("--fix",)),
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
    DiagnosticCode.UNRAISED_EVENT: CodeMeta(
        category="handler_completeness",
        level="info",
        meaning="An event is raised by no aggregate or entity method.",
        rationale=(
            "An event that no method raises is declared and wired but never "
            "produced, so the state change it names never happens."
        ),
        fix=(
            "Raise the event from the aggregate or entity method that makes the "
            "change it records, or remove the event if nothing produces it."
        ),
    ),
    DiagnosticCode.UNSUPPORTED_ELEMENT_CLASS: CodeMeta(
        category="unsupported",
        level="error",
        kind="raise",
        meaning="Registration was given a class that is not a domain element.",
        rationale=(
            "Only classes carrying a domain `element_type` can be registered; a "
            "plain class has no element type for the domain to register."
        ),
        fix=(
            "Decorate the class as a domain element (e.g. `@domain.aggregate`) "
            "before registering it, or register a valid element class."
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
    DiagnosticCode.USAGE_CACHE_BACKED_NO_REPOSITORY: CodeMeta(
        category="usage",
        level="error",
        kind="raise",
        meaning="A repository was requested for a cache-backed projection.",
        rationale=(
            "A cache-backed projection is served from a cache, not a provider, "
            "so it has no repository."
        ),
        fix=(
            "Use `cache_for()` to write and `view_for()` to read a cache-backed "
            "projection; `repository_for()` is for provider-backed elements."
        ),
    ),
    DiagnosticCode.USAGE_DUPLICATE_DATABASE_MODEL: CodeMeta(
        category="usage",
        level="error",
        kind="raise",
        meaning="Two database models target the same aggregate and database.",
        rationale=(
            "An aggregate maps to one database model per database; registering a "
            "second model for the same aggregate and database makes the mapping "
            "ambiguous."
        ),
        fix=(
            "Register one database model per aggregate per database, or target a "
            "different database on the duplicate model."
        ),
    ),
    DiagnosticCode.USAGE_ELEMENT_NOT_REGISTERED: CodeMeta(
        category="usage",
        level="error",
        kind="raise",
        meaning="An accessor was asked for an element the domain has not registered.",
        rationale=(
            "A runtime accessor resolves the element it is given against the "
            "registry; an unregistered element, or a name string instead of the "
            "class, has no entry to resolve."
        ),
        fix=(
            "Pass a registered element class to the accessor, and register the "
            "element with the domain first."
        ),
    ),
    DiagnosticCode.USAGE_ENRICHER_NOT_CALLABLE: CodeMeta(
        category="usage",
        level="error",
        kind="raise",
        meaning="A registered enricher is not callable.",
        rationale=(
            "An enricher is invoked to augment a message or aggregate, so it has "
            "to be callable; a non-callable value cannot be invoked."
        ),
        fix="Register a callable (a function or a callable object) as the enricher.",
    ),
    DiagnosticCode.USAGE_NOT_A_PROJECTION: CodeMeta(
        category="usage",
        level="error",
        kind="raise",
        meaning="A projection-only accessor was given a non-projection element.",
        rationale=(
            "`view_for` and `connection_for` operate on projections; an element "
            "of another type has no read view or projection connection."
        ),
        fix=(
            "Call the accessor with a projection, or use the accessor that "
            "matches the element's type."
        ),
    ),
    DiagnosticCode.USAGE_UNKNOWN_ELEMENT_TYPE: CodeMeta(
        category="usage",
        level="error",
        kind="raise",
        meaning="An element factory was requested for an unknown element type.",
        rationale=(
            "The domain builds elements through a fixed set of type factories; a "
            "type outside that set has no factory to build it."
        ),
        fix="Use one of the supported domain element types.",
    ),
    DiagnosticCode.VALUE_OBJECT_INVARIANT_FAILED: CodeMeta(
        category="invariants",
        level="error",
        kind="raise",
        meaning="An invariant on a value object did not hold when it was built.",
        rationale=(
            "A value object validates its invariants at construction and is "
            "immutable afterward; the values it was built from broke one of those "
            "invariants."
        ),
        fix=(
            "Build the value object from values that satisfy its invariants, or "
            "catch the `ValidationError`. The error messages name what failed."
        ),
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
    location: str | None = None,
    rationale: str | None = None,
    fix: str | None = None,
    suggestion: str | None = None,
) -> Diagnostic:
    """Build one ``_diagnostics`` wire record for ``code``.

    Resolves ``category``/``level``/``rationale``/``fix`` from the registry;
    pass ``level``/``rationale``/``fix`` to override the canonical default at
    a site that diverges. ``suggestion`` defaults to the resolved ``fix``.
    ``location`` names where the diagnostic came from; it is included only when
    given (no lint producer sets it today — it is carried on the exception path
    instead). ``resolving_operation`` is attached automatically from the
    registry for a code that maps to a resolving command, and omitted for one
    that does not. The returned dict carries exactly the wire keys the IR,
    SARIF, and ``check`` output already emit, plus
    ``field``/``location``/``resolving_operation`` when they apply.
    """
    meta = REGISTRY[code]
    resolved_rationale = rationale if rationale is not None else meta.rationale
    resolved_fix = fix if fix is not None else meta.fix
    diagnostic: Diagnostic = {
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
    if location is not None:
        diagnostic["location"] = location
    if meta.resolution is not None:
        diagnostic["resolving_operation"] = meta.resolution.as_wire()
    return diagnostic
