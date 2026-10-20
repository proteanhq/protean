"""Each element accepts only certain kinds of element as its ``part_of`` owner.

A class target of the wrong kind is rejected when the element registers. A
string target resolves only against the allowed kinds when the domain
initializes.
"""

import re

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.process_manager import BaseProcessManager
from protean.exceptions import ConfigurationError, IncorrectUsageError
from protean.fields import Identifier, String
from protean.utils import PART_OF_KINDS, DomainObjects
from protean.utils.mixins import handle

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
        domain.register(target, event_sourced=True)
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

# A database model takes only a class target.
STRING_ROWS = [row for row in ROWS if row != "database model"]

STRING_ALLOWED_CASES = [
    pytest.param(row, kind, id=f"{row}-{kind}")
    for row in STRING_ROWS
    for kind in ROWS[row][2]
]

STRING_DISALLOWED_CASES = [
    pytest.param(row, kind, id=f"{row}-{kind}")
    for row in STRING_ROWS
    for kind in KINDS
    if kind not in ROWS[row][2]
    # An event sourced repository naming a plain aggregate resolves, then
    # fails its own event-sourced check.
    and not (row == "event sourced repository" and kind == AGGREGATE)
]

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


def test_rows_cover_every_element_type_in_the_kinds_table():
    # The repository keeps its own check and message, so it has its own tests.
    row_types = {
        DomainObjects(builder().element_type) for builder, _, _, _ in ROWS.values()
    }
    assert row_types | {DomainObjects.REPOSITORY} == set(PART_OF_KINDS)


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

    @pytest.mark.parametrize("part_of", [0, False, []])
    def test_a_falsy_value_is_rejected(self, test_domain, part_of):
        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(elements.value_object(), part_of=part_of)

        assert str(exc.value) == (
            "Value Object `Price` can only be associated with an Aggregate; "
            f"`{part_of!r}` is not a class"
        )

    def test_a_class_with_an_unhashable_element_type_is_rejected(self, test_domain):
        class Order:
            element_type = []

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(elements.event(), part_of=Order)

        assert str(exc.value) == (
            "Event `OrderPlaced` can only be associated with an Aggregate or a "
            "Process Manager; `Order` is not a domain element"
        )


class TestAbstractTargets:
    def test_entity_cannot_belong_to_an_abstract_aggregate(self, test_domain):
        order = elements.order_aggregate()
        test_domain.register(order, abstract=True)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(elements.entity(), part_of=order)

        assert str(exc.value) == (
            "Entity `Note` can only be associated with an Aggregate or an "
            "Entity; `Order` is abstract"
        )

    @pytest.mark.parametrize("base", [BaseAggregate, BaseEntity])
    def test_entity_cannot_belong_to_a_base_class(self, test_domain, base):
        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(elements.entity(), part_of=base)

        assert str(exc.value) == (
            "Entity `Note` can only be associated with an Aggregate or an "
            f"Entity; `{base.__name__}` is abstract"
        )

    def test_entity_cannot_name_an_abstract_aggregate_by_string(self, test_domain):
        test_domain.register(elements.order_aggregate(), abstract=True)
        test_domain.register(elements.entity(), part_of="Order")

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert str(exc.value) == (
            "Entity `Note` can only be associated with an Aggregate or an "
            "Entity; `Order` is abstract"
        )

    @pytest.mark.parametrize("builder", [elements.event, elements.value_object])
    def test_event_and_value_object_may_belong_to_an_abstract_aggregate(
        self, test_domain, builder
    ):
        order = elements.order_aggregate()
        test_domain.register(order, abstract=True)

        element_cls = test_domain.register(builder(), part_of=order)
        test_domain.init(traverse=False)

        assert element_cls.meta_.part_of is order


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

    @pytest.mark.parametrize("row, kind", STRING_ALLOWED_CASES)
    def test_string_naming_an_allowed_kind_resolves(self, test_domain, row, kind):
        builder, _, _, _ = ROWS[row]
        target = register_target(test_domain, kind)
        element_cls = test_domain.register(builder(), part_of=TARGET_NAMES[kind])
        test_domain.init(traverse=False)

        assert element_cls.meta_.part_of is target

    @pytest.mark.parametrize("row, kind", STRING_DISALLOWED_CASES)
    def test_string_naming_a_disallowed_kind_fails_init(self, test_domain, row, kind):
        builder, _, _, _ = ROWS[row]
        register_target(test_domain, kind)
        target_name = TARGET_NAMES[kind]
        element_cls = test_domain.register(builder(), part_of=target_name)

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        message = str(exc.value)
        assert re.search(
            rf"`{element_cls.__name__}` references `{target_name}` via part_of",
            message,
        ), message

    @pytest.mark.parametrize("kind", [k for k in KINDS if k != AGGREGATE])
    def test_repository_string_naming_a_disallowed_kind_fails_init(
        self, test_domain, kind
    ):
        register_target(test_domain, kind)
        test_domain.register(elements.repository(), part_of=TARGET_NAMES[kind])

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert (
            f"`OrderRepository` references `{TARGET_NAMES[kind]}` via part_of"
            in str(exc.value)
        )

    def test_repository_string_naming_an_aggregate_resolves(self, test_domain):
        order = register_target(test_domain, AGGREGATE)
        repository_cls = test_domain.register(elements.repository(), part_of="Order")
        test_domain.init(traverse=False)

        assert repository_cls.meta_.part_of is order

    def test_event_sourced_repository_string_naming_a_plain_aggregate_fails_init(
        self, test_domain
    ):
        register_target(test_domain, AGGREGATE)
        test_domain.register(elements.event_sourced_repository(), part_of="Order")

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert str(exc.value) == (
            "Repository `AccountRepository` can only be associated with an "
            "Event Sourced Aggregate"
        )

    @pytest.mark.parametrize("builder", [elements.event, elements.command])
    def test_a_name_shared_with_a_process_manager_resolves_to_the_aggregate(
        self, test_domain, builder
    ):
        order = register_target(test_domain, AGGREGATE)
        shipped = test_domain.register(elements.order_shipped_event(), part_of=order)

        class Order(BaseProcessManager):
            order_id: Identifier()

            @handle(shipped, start=True, correlate="order_id")
            def on_shipped(self, event):
                pass

        test_domain.register(Order, stream_categories=["test::order"])
        element_cls = test_domain.register(builder(), part_of="Order")
        test_domain.init(traverse=False)

        assert element_cls.meta_.part_of is order


class TestPartOfCycles:
    def test_entity_naming_itself_fails_init(self, test_domain):
        register_target(test_domain, AGGREGATE)

        class Loop(BaseEntity):
            text: String()

        test_domain.register(Loop, part_of="Loop")

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert "The `part_of` chain `Loop` -> `Loop` loops back on itself" in str(
            exc.value
        )

    def test_entities_naming_each_other_fail_init(self, test_domain):
        register_target(test_domain, AGGREGATE)

        class First(BaseEntity):
            text: String()

        class Second(BaseEntity):
            text: String()

        test_domain.register(First, part_of="Second")
        test_domain.register(Second, part_of="First")

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert "loops back on itself" in str(exc.value)

    def test_entity_given_itself_as_a_class_fails_init(self, test_domain):
        register_target(test_domain, AGGREGATE)

        class Loop(BaseEntity):
            text: String()

        test_domain.register(Loop, part_of=Loop)

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert "The `part_of` chain `Loop` -> `Loop` loops back on itself" in str(
            exc.value
        )
