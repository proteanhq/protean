"""Each element accepts only certain kinds of element as its ``part_of`` owner.

A class target of the wrong kind is rejected when the element registers. A
string target resolves only against the allowed kinds when the domain
initializes.
"""

import re

import pytest

from protean import Domain
from protean.exceptions import ConfigurationError, IncorrectUsageError
from protean.fields import String

from . import elements

AGGREGATE = "aggregate"
ES_AGGREGATE = "event sourced aggregate"
ENTITY = "entity"
VALUE_OBJECT = "value object"
PROJECTION = "projection"
PROCESS_MANAGER = "process manager"

KINDS = (AGGREGATE, ENTITY, VALUE_OBJECT, PROJECTION, PROCESS_MANAGER)

TARGET_NAMES = {
    AGGREGATE: "Order",
    ES_AGGREGATE: "Account",
    ENTITY: "LineItem",
    VALUE_OBJECT: "Money",
    PROJECTION: "OrderSummary",
    PROCESS_MANAGER: "Fulfillment",
}

TARGET_KIND_TEXT = {
    AGGREGATE: "is an Aggregate",
    ENTITY: "is an Entity",
    VALUE_OBJECT: "is a Value Object",
    PROJECTION: "is a Projection",
    PROCESS_MANAGER: "is a Process Manager",
}


def register_target(domain, kind):
    """Register a target of ``kind`` with ``domain`` and return its class."""
    if kind == AGGREGATE:
        target = elements.order_aggregate()
        domain.register(target)
    elif kind == ES_AGGREGATE:
        target = elements.account_es_aggregate()
        domain.register(target, is_event_sourced=True)
    elif kind == ENTITY:
        order = elements.order_aggregate()
        domain.register(order)
        target = elements.line_item_entity()
        domain.register(target, part_of=order)
    elif kind == VALUE_OBJECT:
        target = elements.money_value_object()
        domain.register(target)
    elif kind == PROJECTION:
        target = elements.order_summary_projection()
        domain.register(target)
    elif kind == PROCESS_MANAGER:
        order = elements.order_aggregate()
        domain.register(order)
        shipped = elements.order_shipped_event()
        domain.register(shipped, part_of=order)
        target = elements.fulfillment_process_manager(shipped)
        domain.register(target, stream_categories=["test::order"])
    else:  # pragma: no cover - guards the table below
        raise AssertionError(f"unknown target kind {kind}")
    return target


# (element builder, element label, allowed target kinds, allowed-kinds phrase)
ROWS = {
    "value object": (
        elements.value_object,
        "Value Object",
        (AGGREGATE,),
        "an Aggregate",
    ),
    "application service": (
        elements.application_service,
        "Application Service",
        (AGGREGATE,),
        "an Aggregate",
    ),
    "command handler": (
        elements.command_handler,
        "Command Handler",
        (AGGREGATE,),
        "an Aggregate",
    ),
    "event handler": (
        elements.event_handler,
        "Event Handler",
        (AGGREGATE,),
        "an Aggregate",
    ),
    "event sourced repository": (
        elements.event_sourced_repository,
        "Event Sourced Repository",
        (ES_AGGREGATE,),
        "an Aggregate",
    ),
    "entity": (
        elements.entity,
        "Entity",
        (AGGREGATE, ENTITY),
        "an Aggregate or an Entity",
    ),
    "event": (
        elements.event,
        "Event",
        (AGGREGATE, PROCESS_MANAGER),
        "an Aggregate or a Process Manager",
    ),
    "command": (
        elements.command,
        "Command",
        (AGGREGATE, PROCESS_MANAGER),
        "an Aggregate or a Process Manager",
    ),
    "database model": (
        elements.database_model,
        "Database Model",
        (AGGREGATE, ENTITY, PROJECTION),
        "an Aggregate, an Entity or a Projection",
    ),
    "query": (
        elements.query,
        "Query",
        (PROJECTION,),
        "a Projection",
    ),
    "query handler": (
        elements.query_handler,
        "Query Handler",
        (PROJECTION,),
        "a Projection",
    ),
}

ALLOWED_CASES = [
    pytest.param(row, kind, id=f"{row}-{kind}")
    for row, (_, _, allowed, _) in ROWS.items()
    for kind in allowed
]

DISALLOWED_CASES = [
    pytest.param(row, kind, id=f"{row}-{kind}")
    for row, (_, _, allowed, _) in ROWS.items()
    for kind in KINDS
    if kind not in allowed
    # An event sourced repository's aggregate case keeps its own message.
    and not (row == "event sourced repository" and kind == AGGREGATE)
]


@pytest.mark.parametrize("row, kind", ALLOWED_CASES)
def test_allowed_class_target_registers_and_initializes(test_domain, row, kind):
    builder, _, _, _ = ROWS[row]
    target = register_target(test_domain, kind)

    element_cls = test_domain.register(builder(), part_of=target)
    test_domain.init(traverse=False)

    assert element_cls.meta_.part_of is target


@pytest.mark.parametrize("row, kind", DISALLOWED_CASES)
def test_disallowed_class_target_is_rejected_at_registration(test_domain, row, kind):
    builder, label, _, phrase = ROWS[row]
    target = register_target(test_domain, kind)
    element_cls = builder()

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(element_cls, part_of=target)

    assert str(exc.value) == (
        f"{label} `{element_cls.__name__}` can only be associated with "
        f"{phrase}; `{TARGET_NAMES[kind]}` {TARGET_KIND_TEXT[kind]}"
    )


def test_disallowed_cases_cover_every_row():
    rows_with_a_rejection = {param.values[0] for param in DISALLOWED_CASES}
    assert rows_with_a_rejection == set(ROWS)


class TestRepositoryChecksAreUnchanged:
    def test_repository_rejects_a_non_aggregate_with_its_existing_message(
        self, test_domain
    ):
        target = register_target(test_domain, ENTITY)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(elements.repository(), part_of=target)

        assert str(exc.value) == (
            "Repository `OrderRepository` can only be associated with an Aggregate"
        )

    def test_repository_rejects_a_non_class_with_its_existing_message(
        self, test_domain
    ):
        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(elements.repository(), part_of=object())

        assert str(exc.value) == (
            "Repository `OrderRepository` can only be associated with an Aggregate"
        )

    def test_repository_accepts_an_aggregate(self, test_domain):
        target = register_target(test_domain, AGGREGATE)
        repository_cls = test_domain.register(elements.repository(), part_of=target)
        test_domain.init(traverse=False)

        assert repository_cls.meta_.part_of is target

    def test_event_sourced_repository_keeps_its_message_for_a_plain_aggregate(
        self, test_domain
    ):
        target = register_target(test_domain, AGGREGATE)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(elements.event_sourced_repository(), part_of=target)

        assert str(exc.value) == (
            "Repository `AccountRepository` can only be associated with an "
            "Event Sourced Aggregate"
        )


class TestTargetsThatAreNotDomainElements:
    def test_a_plain_class_is_rejected(self, test_domain):
        class Order:
            pass

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(elements.event(), part_of=Order)

        assert str(exc.value) == (
            "Event `OrderPlaced` can only be associated with an Aggregate or a "
            "Process Manager; `Order` is not a domain element"
        )

    def test_an_instance_is_rejected(self, test_domain):
        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(elements.entity(), part_of=42)

        assert str(exc.value) == (
            "Entity `Note` can only be associated with an Aggregate or an "
            "Entity; `42` is not a class"
        )

    def test_an_element_kind_outside_the_table_is_named(self, test_domain):
        query_cls = elements.query()

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(elements.value_object(), part_of=query_cls)

        assert str(exc.value) == (
            "Value Object `Price` can only be associated with an Aggregate; "
            "`GetOrder` is a Query"
        )


class TestElementsWithoutAnOwner:
    def test_value_object_without_part_of_still_registers(self, test_domain):
        vo_cls = test_domain.register(elements.value_object())
        test_domain.init(traverse=False)

        assert vo_cls.meta_.part_of is None

    def test_abstract_event_without_part_of_still_registers(self, test_domain):
        event_cls = test_domain.register(elements.event(), abstract=True)

        assert event_cls.meta_.part_of is None

    def test_event_handler_on_a_stream_still_registers(self, test_domain):
        handler_cls = test_domain.register(
            elements.event_handler(), stream_category="test::order"
        )
        test_domain.init(traverse=False)

        assert handler_cls.meta_.part_of is None

    def test_auto_constructed_elements_for_entities_and_projections_register(
        self, test_domain
    ):
        register_target(test_domain, ENTITY)
        projection_cls = register_target(test_domain, PROJECTION)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            assert test_domain.repository_for(projection_cls) is not None


@pytest.mark.no_test_domain
def test_issue_repro_raises_incorrect_usage_at_registration():
    domain = Domain(name="Repro")

    @domain.aggregate
    class Order:
        name: String()

    @domain.value_object
    class Money:
        amount: String()

    with pytest.raises(IncorrectUsageError) as exc:

        @domain.event(part_of=Money)
        class OrderPlaced:
            order_id: String()

    assert str(exc.value) == (
        "Event `OrderPlaced` can only be associated with an Aggregate or a "
        "Process Manager; `Money` is a Value Object"
    )


class TestStringTargets:
    def test_entity_names_a_parent_entity(self, test_domain):
        order = register_target(test_domain, AGGREGATE)
        line_item = test_domain.register(elements.line_item_entity(), part_of=order)
        note = test_domain.register(elements.entity(), part_of="LineItem")
        test_domain.init(traverse=False)

        assert note.meta_.part_of is line_item
        assert note.meta_.aggregate_cluster is order

    def test_entity_naming_a_parent_entity_matches_the_class_form(self, test_domain):
        order = register_target(test_domain, AGGREGATE)
        line_item = test_domain.register(elements.line_item_entity(), part_of=order)
        note = test_domain.register(elements.entity(), part_of="LineItem")
        test_domain.init(traverse=False)

        reference = note.__dict__["line_item"]
        assert reference.to_cls is line_item

    @pytest.mark.parametrize("builder", [elements.event, elements.command])
    def test_event_and_command_name_a_process_manager(self, test_domain, builder):
        pm_cls = register_target(test_domain, PROCESS_MANAGER)
        element_cls = test_domain.register(builder(), part_of="Fulfillment")
        test_domain.init(traverse=False)

        assert element_cls.meta_.part_of is pm_cls
        assert element_cls.meta_.aggregate_cluster is pm_cls

    @pytest.mark.parametrize(
        "builder, target_kind",
        [
            pytest.param(elements.value_object, ENTITY, id="value-object-entity"),
            pytest.param(elements.event, VALUE_OBJECT, id="event-value-object"),
            pytest.param(elements.command, ENTITY, id="command-entity"),
            pytest.param(elements.entity, PROJECTION, id="entity-projection"),
            pytest.param(elements.command_handler, ENTITY, id="handler-entity"),
            pytest.param(
                elements.application_service,
                PROCESS_MANAGER,
                id="app-service-process-manager",
            ),
        ],
    )
    def test_string_naming_a_disallowed_kind_fails_init(
        self, test_domain, builder, target_kind
    ):
        register_target(test_domain, target_kind)
        target_name = TARGET_NAMES[target_kind]
        element_cls = test_domain.register(builder(), part_of=target_name)

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        message = str(exc.value)
        assert re.search(
            rf"`{element_cls.__name__}` references `{target_name}` via part_of",
            message,
        ), message
