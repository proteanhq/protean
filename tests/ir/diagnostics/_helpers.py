"""Shared builders and fixtures for the diagnostics tests."""

from protean import Domain, handle
from protean.core.aggregate import apply
from protean.fields import Identifier, List, Reference
from protean.fields.simple import Float, String
from protean.ir.builder import IRBuilder
from tests.ir.support import (
    infra_import_domain,
)

_FIXTURES = "tests.ir.custom_lint_fixtures"

_BUILTIN_CODES = frozenset(
    {
        "UNHANDLED_EVENT",
        "UNUSED_COMMAND",
        "ES_EVENT_MISSING_APPLY",
        "PUBLISHED_NO_EXTERNAL_BROKER",
        "AGGREGATE_WITHOUT_COMMAND_HANDLER",
        "PROJECTION_WITHOUT_PROJECTOR",
        "AGGREGATE_TOO_LARGE",
        "HANDLER_TOO_BROAD",
        "EVENT_WITHOUT_DATA",
        "UPCASTER_GAP",
        "DEPRECATED_ELEMENT",
        "DEPRECATED_FIELD",
        "DEPRECATED_OPTION",
        "DEPRECATED_EMAIL",
        "CROSS_AGGREGATE_REFERENCE",
        "ES_AGGREGATE_NO_EVENTS",
        "VALUE_OBJECT_MUTABLE_FIELD",
        "AGGREGATE_NO_INVARIANTS",
        "CIRCULAR_CLUSTER_DEPENDENCY",
        "INFRA_IMPORT_IN_DOMAIN",
        "QUERY_HANDLER_WITHOUT_QUERY",
        "PROJECTOR_HANDLES_ORPHANED_EVENT",
        "COMMAND_HANDLER_CROSS_CLUSTER",
        "SUBSCRIBER_NO_STREAMS",
        "PROCESS_MANAGER_UNCLOSED",
        "EVENT_NOT_PAST_TENSE",
        "COMMAND_NOT_IMPERATIVE",
        "AGGREGATE_NOT_NOUN",
    }
)


def build_diagnostics_test_domain() -> Domain:
    """Build a domain with unhandled events and unused commands."""
    domain = Domain(name="DiagTest", root_path=".")

    @domain.event(part_of="Order")
    class OrderPlaced:
        order_id = Identifier(identifier=True)

    @domain.event(part_of="Order")
    class OrderCancelled:
        order_id = Identifier(identifier=True)

    @domain.command(part_of="Order")
    class PlaceOrder:
        customer_name = String(required=True)

    @domain.aggregate
    class Order:
        customer_name = String(max_length=100, required=True)
        total = Float(min_value=0.0)

    domain.init(traverse=False)
    return domain


def _build_domain_with_rules(rules: list[str]) -> Domain:
    """Helper: build a minimal domain with custom lint rules configured."""
    domain = Domain(name="CustomRuleTest", root_path=".")
    domain.config["lint"] = {"rules": rules}

    @domain.aggregate
    class Widget:
        label = String(max_length=50)

    domain.init(traverse=False)
    return domain


def build_all_categories_domain() -> Domain:
    """A domain that emits at least one diagnostic per built-in category."""
    domain = Domain(name="AllCategories", root_path=".")

    @domain.aggregate(deprecated={"since": "0.15", "removal": "1.0"})
    class Order:  # deprecation + handler_completeness (no command handler)
        name = String(max_length=100)

    @domain.event(part_of=Order)
    class OrderNudged:  # aggregate_design (EVENT_WITHOUT_DATA) + UNHANDLED_EVENT
        pass

    @domain.event(part_of=Order)
    class OrderPlaced:  # versioning (UPCASTER_GAP) + UNHANDLED_EVENT
        __version__ = 2
        name = String()

    domain.init(traverse=False)
    return domain


def _build_aggregate_design_domain() -> Domain:
    """Emits all four aggregate-design fitness-function codes so the shared
    schema-enrichment assertions cover their emit sites too.

    ``CROSS_AGGREGATE_REFERENCE`` (Customer→Order), ``ES_AGGREGATE_NO_EVENTS``
    (event-sourced Ledger with no events), ``VALUE_OBJECT_MUTABLE_FIELD``
    (a VO with a ``List`` field), and ``AGGREGATE_NO_INVARIANTS`` (every
    aggregate here lacks invariants).
    """
    domain = Domain(name="AggregateDesign", root_path=".")

    @domain.aggregate
    class Order:
        total = Float()

    @domain.aggregate
    class Customer:
        name = String()
        order = Reference(Order)  # CROSS_AGGREGATE_REFERENCE

    @domain.aggregate(event_sourced=True)
    class Ledger:  # ES_AGGREGATE_NO_EVENTS — no events declared
        balance = Float()

    @domain.value_object(part_of=Order)
    class ShippingLabel:
        carrier = String()
        tags = List()  # VALUE_OBJECT_MUTABLE_FIELD

    domain.init(traverse=False)
    return domain


def _build_completeness_domain() -> Domain:
    """Emits UNUSED_COMMAND, PUBLISHED_NO_EXTERNAL_BROKER,
    PROJECTION_WITHOUT_PROJECTOR, AGGREGATE_TOO_LARGE, HANDLER_TOO_BROAD,
    DEPRECATED_FIELD (plus AGGREGATE_WITHOUT_COMMAND_HANDLER)."""
    domain = Domain(name="EnrichCompleteness", root_path=".")
    domain.config["lint"] = {"aggregate_size_limit": 1, "handler_breadth_limit": 1}

    @domain.aggregate
    class Order:
        legacy = String(max_length=10, deprecated="0.15")  # DEPRECATED_FIELD

    @domain.entity(part_of=Order)
    class LineItem:  # two entities > size limit 1 → AGGREGATE_TOO_LARGE
        sku = String(max_length=10)

    @domain.entity(part_of=Order)
    class Discount:
        code = String(max_length=10)

    @domain.command(part_of=Order)
    class PlaceOrder:
        name = String(required=True)

    @domain.command(part_of=Order)
    class CancelOrder:
        name = String(required=True)

    @domain.command(part_of=Order)
    class ArchiveOrder:  # no handler → UNUSED_COMMAND
        name = String(required=True)

    @domain.command_handler(part_of=Order)
    class OrderHandler:  # handles 2 > breadth limit 1 → HANDLER_TOO_BROAD
        @handle(PlaceOrder)
        def place(self, command):
            pass

        @handle(CancelOrder)
        def cancel(self, command):
            pass

    @domain.event(part_of=Order, published=True)
    class OrderShipped:  # published, no external broker → PUBLISHED_NO_EXTERNAL_BROKER
        order_id = Identifier(required=True)

    @domain.projection
    class OrderView:  # no projector → PROJECTION_WITHOUT_PROJECTOR
        order_id = Identifier(identifier=True)

    domain.init(traverse=False)
    return domain


def _build_es_domain() -> Domain:
    """Emits ES_EVENT_MISSING_APPLY and DEPRECATED_OPTION (the ``is_event_sourced``
    alias emit site in ``_diagnose_deprecated_options``)."""
    import warnings

    domain = Domain(name="EnrichEs", root_path=".")

    @domain.event(part_of="Wallet")
    class WalletCreated:
        wallet_id = Identifier(identifier=True)

    @domain.event(part_of="Wallet")
    class FundsAdded:
        amount = Float(required=True)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # `is_event_sourced` alias is deprecated

        @domain.aggregate(is_event_sourced=True)  # alias → DEPRECATED_OPTION
        class Wallet:
            balance = Float(default=0.0)

            @apply
            def created(self, event: WalletCreated) -> None:  # no @apply for FundsAdded
                pass

    domain.init(traverse=False)
    return domain


def _build_flow_fitness_domain() -> Domain:
    """Emits QUERY_HANDLER_WITHOUT_QUERY, PROJECTOR_HANDLES_ORPHANED_EVENT,
    and PROCESS_MANAGER_UNCLOSED (the 3.5.4 rules exercised for schema
    enrichment)."""
    domain = Domain(name="EnrichFlowFitness", root_path=".")

    @domain.aggregate
    class Order:
        name = String(max_length=50)

    @domain.event(part_of=Order)
    class OrderPlaced:
        order_id = Identifier(identifier=True)

    @domain.projection
    class OrderView:
        order_id = Identifier(identifier=True)

    @domain.projector(projector_for=OrderView, aggregates=[Order])
    class OrderViewProjector:
        @handle(OrderPlaced)
        def on_placed(self, event):
            pass

    @domain.query_handler(part_of=OrderView)  # no query → QUERY_HANDLER_WITHOUT_QUERY
    class OrderViewQueryHandler:
        pass

    @domain.process_manager(
        stream_categories=["order"]
    )  # no end → PROCESS_MANAGER_UNCLOSED
    class OrderSaga:
        order_id = Identifier()

        @handle(OrderPlaced, start=True, correlate="order_id")
        def on_placed(self, event):
            self.order_id = event.order_id

    domain.init(traverse=False)

    # An orphaned projector handler key (a stale ``__type__`` no live domain can
    # register) only exists in materialized IR — inject it so the enrichment
    # sweep covers the PROJECTOR_HANDLES_ORPHANED_EVENT emit site.
    method = next(iter(OrderViewProjector._handlers[OrderPlaced.__type__]))
    OrderViewProjector._handlers["EnrichFlowFitness.RemovedEvent.v1"].add(method)

    return domain


def _all_builtin_diagnostics() -> list[dict]:
    """Diagnostics covering every built-in code, merged from focused domains.

    A single domain cannot naturally emit all built-in codes without
    interactions, so each code (or small compatible group) gets a minimal
    domain. The merged list drives the schema-enrichment assertions across
    *every* emit site — including the second ``DEPRECATED_OPTION`` site
    (command ``published``) and ``DEPRECATED_EMAIL``, which are otherwise
    unasserted.
    """
    import warnings

    diagnostics: list[dict] = []
    diagnostics += IRBuilder(build_all_categories_domain()).build()["diagnostics"]
    diagnostics += IRBuilder(_build_completeness_domain()).build()["diagnostics"]
    diagnostics += IRBuilder(_build_es_domain()).build()["diagnostics"]
    diagnostics += IRBuilder(_build_aggregate_design_domain()).build()["diagnostics"]

    # DEPRECATED_OPTION — command ``published`` emit site (distinct dict from
    # the aggregate-alias site above; both are hand-copied and must be checked).
    cmd_domain = Domain(name="EnrichCmdOption", root_path=".")

    @cmd_domain.aggregate
    class Order:
        name = String(max_length=10)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        @cmd_domain.command(part_of=Order, published=True)
        class PlaceOrder:
            name = String(required=True)

    cmd_domain.init(traverse=False)
    diagnostics += IRBuilder(cmd_domain).build()["diagnostics"]

    # DEPRECATED_EMAIL — the email subsystem is itself deprecated.
    email_domain = Domain(name="EnrichEmail")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        @email_domain.email
        class WelcomeMail:
            pass

    email_domain.init(traverse=False)
    diagnostics += IRBuilder(email_domain).build()["diagnostics"]

    # CIRCULAR_CLUSTER_DEPENDENCY — a 2-cluster identity-reference cycle.
    cycle_domain = Domain(name="EnrichCycle", root_path=".")

    @cycle_domain.aggregate
    class CycleOrder:
        name = String(max_length=10)
        customer = Reference("CycleCustomer")

    @cycle_domain.aggregate
    class CycleCustomer:
        name = String(max_length=10)
        order = Reference("CycleOrder")

    cycle_domain.init(traverse=False)
    diagnostics += IRBuilder(cycle_domain).build()["diagnostics"]

    # INFRA_IMPORT_IN_DOMAIN — opt-in; the fixture module imports protean.adapters.
    infra_domain = Domain(name="EnrichInfra", root_path=".")
    infra_domain.config["lint"] = {"check_infra_imports": True}
    infra_domain.register(infra_import_domain.Money)
    infra_domain.register(infra_import_domain.InfraOrder)
    infra_domain.init(traverse=False)
    diagnostics += IRBuilder(infra_domain).build()["diagnostics"]

    # 3.5.4 flow-fitness rules reachable from a live domain.
    diagnostics += IRBuilder(_build_flow_fitness_domain()).build()["diagnostics"]

    # SUBSCRIBER_NO_STREAMS — the subscriber factory hard-requires a stream, so
    # null it post-init to reach the materialized-IR state the rule guards.
    sub_domain = Domain(name="EnrichSubscriber", root_path=".")

    @sub_domain.subscriber(broker="default", stream="payments")
    class PaymentSubscriber:
        def __call__(self, payload):
            pass

    sub_domain.init(traverse=False)
    PaymentSubscriber.meta_.stream = None
    diagnostics += IRBuilder(sub_domain).build()["diagnostics"]

    # COMMAND_HANDLER_CROSS_CLUSTER — handler_setup forbids a handler targeting
    # another cluster's command, so inject the foreign command type into the
    # handler map (the state stored/hand-edited IR can carry).
    xc_domain = Domain(name="EnrichCrossCluster", root_path=".")

    @xc_domain.aggregate
    class Order:
        name = String(max_length=50)

    @xc_domain.aggregate
    class Shipment:
        name = String(max_length=50)

    @xc_domain.command(part_of=Order)
    class PlaceOrder:
        order_id = Identifier(identifier=True)

    @xc_domain.command(part_of=Shipment)
    class DispatchShipment:
        shipment_id = Identifier(identifier=True)

    @xc_domain.command_handler(part_of=Order)
    class OrderCommandHandler:
        @handle(PlaceOrder)
        def place(self, command):
            pass

    xc_domain.init(traverse=False)
    method = next(iter(OrderCommandHandler._handlers[PlaceOrder.__type__]))
    OrderCommandHandler._handlers[DispatchShipment.__type__].add(method)
    diagnostics += IRBuilder(xc_domain).build()["diagnostics"]

    # Naming conventions — one domain emits all three info-level naming codes.
    naming_domain = Domain(name="EnrichNaming", root_path=".")

    @naming_domain.event(part_of="OrderProcessing")
    class OrderShipping:  # gerund → EVENT_NOT_PAST_TENSE
        order_id = Identifier(identifier=True)

    @naming_domain.command(part_of="OrderProcessing")
    class OrderCommand:  # non-imperative → COMMAND_NOT_IMPERATIVE
        order_id = Identifier(identifier=True)

    @naming_domain.aggregate
    class OrderProcessing:  # gerund → AGGREGATE_NOT_NOUN
        name = String(max_length=50)

    naming_domain.init(traverse=False)
    diagnostics += IRBuilder(naming_domain).build()["diagnostics"]

    return diagnostics


def _codes_for(ir: dict, element_substr: str) -> list[str]:
    """Codes of diagnostics whose element FQN contains ``element_substr``."""
    return [
        d["code"] for d in ir["diagnostics"] if element_substr in d.get("element", "")
    ]


def _build_five_finding_domain(suppressions: dict | None = None) -> Domain:
    """Domain with five AGGREGATE_WITHOUT_COMMAND_HANDLER findings.

    One per aggregate (OrderA..OrderE), so the total order over survivors is
    by aggregate FQN — deterministic and independent of rule execution order.
    """
    domain = Domain(name="AllowList", root_path=".")

    @domain.aggregate
    class OrderA:
        name = String(max_length=50)

    @domain.aggregate
    class OrderB:
        name = String(max_length=50)

    @domain.aggregate
    class OrderC:
        name = String(max_length=50)

    @domain.aggregate
    class OrderD:
        name = String(max_length=50)

    @domain.aggregate
    class OrderE:
        name = String(max_length=50)

    if suppressions is not None:
        domain.config["lint"] = {"suppressions": suppressions}

    domain.init(traverse=False)
    return domain


def _circular_findings(ir: dict) -> list[dict]:
    return [d for d in ir["diagnostics"] if d["code"] == "CIRCULAR_CLUSTER_DEPENDENCY"]


def _infra_findings(ir: dict) -> list[dict]:
    return [d for d in ir["diagnostics"] if d["code"] == "INFRA_IMPORT_IN_DOMAIN"]


def _build_infra_domain(name: str, lint: dict | None = None, **register_kwargs):
    """Register the infra-importing fixture aggregate (and its embedded value
    object) onto a fresh domain. ``register_kwargs`` flow to the aggregate."""
    domain = Domain(name=name, root_path=".")
    if lint is not None:
        domain.config["lint"] = lint
    domain.register(infra_import_domain.Money)
    domain.register(infra_import_domain.InfraOrder, **register_kwargs)
    domain.init(traverse=False)
    return domain


def _findings(ir: dict, code: str) -> list[dict]:
    """Diagnostics carrying the given code."""
    return [d for d in ir["diagnostics"] if d["code"] == code]


def _assert_naming_diagnostic_shape(diag: dict) -> None:
    """Assert a naming-convention diagnostic carries the full #774 key set."""
    assert diag["category"] == "naming_conventions"
    assert diag["level"] == "info"
    assert diag["element"], "element FQN must be non-empty"
    assert diag["message"], "message must be non-empty"
    assert diag["rule"]["rationale"], "rule.rationale must be non-empty"
    assert diag["rule"]["fix"], "rule.fix must be non-empty"
    assert diag["suggestion"] == diag["rule"]["fix"]
