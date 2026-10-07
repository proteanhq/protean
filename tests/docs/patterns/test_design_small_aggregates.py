"""Run the examples on ``docs/patterns/design-small-aggregates.md``."""

import pytest

from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import HasMany, HasOne, ValueObject
from protean.utils.reflection import declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _context(example):
    domain = example.domain
    domain.init(traverse=False)
    return domain.domain_context()


def _field_kinds(cls):
    # A plain field reports its kind ("identifier", "auto", ...). An
    # association or value object field reports its class name.
    return {
        name: getattr(field, "field_kind", type(field).__name__)
        for name, field in declared_fields(cls).items()
    }


def _no_cross_aggregate_associations(cls):
    # HasMany/HasOne are only for entities inside the aggregate. None may
    # point at another aggregate.
    for field in declared_fields(cls).values():
        if isinstance(field, (HasMany, HasOne)):
            assert field.to_cls.element_type.name == "ENTITY"
            assert field.to_cls.meta_.part_of is cls


# Reference by identity, and the command that carries the caller's data


def test_order_refers_to_customer_by_identity():
    example = load_example("patterns/design-small-aggregates/001.py")
    with _context(example):
        fields = _field_kinds(example.Order)
        assert set(fields) == {"order_id", "customer_id", "items", "status", "total"}
        assert fields["customer_id"] == "identifier"
        assert "customer" not in fields
        _no_cross_aggregate_associations(example.Order)


def test_order_requires_a_customer_id():
    example = load_example("patterns/design-small-aggregates/001.py")
    with _context(example):
        with pytest.raises(ValidationError) as exc:
            example.Order()
        assert exc.value.messages == {"customer_id": ["is required"]}


def test_command_carries_the_customer_data():
    example = load_example("patterns/design-small-aggregates/001.py")
    with _context(example):
        assert set(declared_fields(example.PlaceOrder)) == {
            "order_id",
            "customer_id",
            "customer_name",
            "customer_email",
            "items",
        }
        with pytest.raises(ValidationError) as exc:
            example.PlaceOrder(order_id="o1", customer_id="c1", items=[])
        assert set(exc.value.messages) >= {"customer_name", "customer_email"}


def _place(example, customer_id):
    example.domain.process(
        example.PlaceOrder(
            order_id="o1",
            customer_id=customer_id,
            customer_name="Ada",
            customer_email="ada@example.com",
            items=[{"product_id": "p1", "quantity": 2}],
        )
    )


def test_handler_places_order_for_customer_in_good_standing():
    example = load_example("patterns/design-small-aggregates/001.py")
    with _context(example):
        domain = example.domain
        domain.repository_for(example.CustomerCreditView).add(
            example.CustomerCreditView(customer_id="c1", credit_status="active")
        )

        _place(example, "c1")

        order = domain.repository_for(example.Order).get("o1")
        assert order.customer_id == "c1"
        assert [(i.product_id, i.quantity) for i in order.items] == [("p1", 2)]


def test_handler_refuses_customer_with_suspended_credit():
    example = load_example("patterns/design-small-aggregates/001.py")
    with _context(example):
        domain = example.domain
        domain.repository_for(example.CustomerCreditView).add(
            example.CustomerCreditView(customer_id="c2", credit_status="suspended")
        )

        with pytest.raises(ValidationError) as exc:
            _place(example, "c2")

        assert exc.value.messages == {"customer_id": ["Customer credit is suspended"]}
        assert domain.repository_for(example.Order).query.all().total == 0


# Option 2: a snapshot value object


def test_snapshot_is_a_value_object_and_does_not_follow_later_edits():
    example = load_example("patterns/design-small-aggregates/002.py")
    with _context(example):
        fields = declared_fields(example.Order)
        assert isinstance(fields["customer"], ValueObject)
        assert fields["customer"].value_object_cls is example.CustomerSnapshot
        _no_cross_aggregate_associations(example.Order)

        snapshot = example.CustomerSnapshot(
            customer_id="c1", name="Ada", email="ada@example.com"
        )
        order = example.Order(customer=snapshot)
        assert order.customer.name == "Ada"

        with pytest.raises(IncorrectUsageError, match="immutable"):
            snapshot.name = "Grace"
        assert order.customer.name == "Ada"


# The Identifier field


@pytest.mark.parametrize(
    "cls_name, references",
    [
        ("Order", {"customer_id", "product_id"}),
        ("Shipment", {"order_id", "carrier_id"}),
    ],
)
def test_each_aggregate_refers_to_others_by_identifier(cls_name, references):
    example = load_example("patterns/design-small-aggregates/003.py")
    with _context(example):
        cls = getattr(example, cls_name)
        fields = _field_kinds(cls)
        for name in references:
            assert fields[name] == "identifier"
            assert declared_fields(cls)[name].required is True
        _no_cross_aggregate_associations(cls)


# Entities for real composition


def test_draft_order_without_items_is_valid_and_items_are_added():
    example = load_example("patterns/design-small-aggregates/004.py")
    with _context(example):
        order = example.Order(customer_id="c1")
        assert order.status == "draft"
        order.add_item("p1", "Pen", 3, 1.5)
        assert [(i.product_name, i.quantity) for i in order.items] == [("Pen", 3)]
        _no_cross_aggregate_associations(example.Order)


def test_non_draft_order_must_have_items():
    example = load_example("patterns/design-small-aggregates/004.py")
    with _context(example):
        order = example.Order(customer_id="c1")
        with pytest.raises(ValidationError) as exc:
            order.status = "placed"
        assert exc.value.messages == {"items": ["Order must have at least one item"]}


def test_item_quantity_must_be_at_least_one():
    example = load_example("patterns/design-small-aggregates/004.py")
    with _context(example):
        order = example.Order(customer_id="c1")
        with pytest.raises(ValidationError) as exc:
            order.add_item("p1", "Pen", 0, 1.5)
        assert "quantity" in exc.value.messages
        assert list(order.items) == []


# Value objects for embedded data


def test_total_and_shipping_address_are_value_objects():
    example = load_example("patterns/design-small-aggregates/005.py")
    with _context(example):
        fields = declared_fields(example.Order)
        assert fields["total"].value_object_cls is example.Money
        assert fields["shipping_address"].value_object_cls is example.ShippingAddress
        _no_cross_aggregate_associations(example.Order)

        order = example.Order(
            customer_id="c1",
            total=example.Money(amount=12.5, currency="USD"),
            shipping_address=example.ShippingAddress(
                street="1 Main St",
                city="Springfield",
                state="IL",
                postal_code="62701",
                country="US",
            ),
        )
        assert order.total.amount == 12.5
        assert order.shipping_address.city == "Springfield"

        with pytest.raises(ValidationError) as exc:
            example.Money(amount=1.0, currency="DOLLARS")
        assert "currency" in exc.value.messages


# Domain events across aggregates


def _draft_order(example):
    order = example.Order(
        order_id="o1",
        customer_id="c1",
        total=example.Money(amount=42.9, currency="USD"),
        items=[{"product_id": "p1", "quantity": 2}],
    )
    return order


def test_placing_an_order_raises_order_placed():
    example = load_example("patterns/design-small-aggregates/006.py")
    with _context(example):
        order = _draft_order(example)
        order.place()

        assert order.status == "placed"
        assert len(order._events) == 1
        event = order._events[0]
        assert isinstance(event, example.OrderPlaced)
        assert event.order_id == "o1"
        assert event.customer_id == "c1"
        assert event.total_amount == 42.9
        assert event.items == [{"product_id": "p1", "quantity": 2}]


def test_only_draft_orders_can_be_placed():
    example = load_example("patterns/design-small-aggregates/006.py")
    with _context(example):
        order = _draft_order(example)
        order.place()

        with pytest.raises(ValidationError) as exc:
            order.place()
        assert exc.value.messages == {"status": ["Only draft orders can be placed"]}
        assert len(order._events) == 1


def test_order_placed_adds_loyalty_points_in_the_other_aggregate():
    example = load_example("patterns/design-small-aggregates/006.py")
    with _context(example):
        domain = example.domain
        loyalty_repo = domain.repository_for(example.CustomerLoyalty)
        loyalty_repo.add(example.CustomerLoyalty(customer_id="c1", points=5))

        order = _draft_order(example)
        order.place()
        domain.repository_for(example.Order).add(order)

        assert loyalty_repo.get("c1").points == 5 + 42


def test_loyalty_handler_listens_on_the_order_stream():
    example = load_example("patterns/design-small-aggregates/006.py")
    with _context(example):
        handler = example.CustomerLoyaltyEventHandler
        assert handler.meta_.stream_category == "smallaggregatesevents::order"
        assert handler.meta_.stream_category == example.Order.meta_.stream_category
        _no_cross_aggregate_associations(example.Order)
        assert not any(
            isinstance(f, (HasMany, HasOne))
            for f in declared_fields(example.CustomerLoyalty).values()
        )


# The two-aggregate rule


def test_place_order_changes_order_and_event_reserves_inventory():
    example = load_example("patterns/design-small-aggregates/007.py")
    with _context(example):
        domain = example.domain
        inventory_repo = domain.repository_for(example.Inventory)
        inventory_repo.add(example.Inventory(product_id="p1", available=10))
        inventory_repo.add(example.Inventory(product_id="p2", available=4))

        domain.process(
            example.PlaceOrder(
                order_id="o1",
                items=[
                    {"product_id": "p1", "quantity": 3},
                    {"product_id": "p2", "quantity": 1},
                ],
            )
        )

        assert domain.repository_for(example.Order).get("o1").status == "placed"
        p1 = inventory_repo.get("p1")
        p2 = inventory_repo.get("p2")
        assert (p1.available, p1.reserved) == (7, 3)
        assert (p2.available, p2.reserved) == (3, 1)


def test_command_handler_touches_only_the_order():
    example = load_example("patterns/design-small-aggregates/007.py")
    with _context(example):
        assert example.OrderCommandHandler.meta_.part_of is example.Order
        assert example.InventoryEventHandler.meta_.part_of is example.Inventory
        assert (
            example.InventoryEventHandler.meta_.stream_category
            == example.Order.meta_.stream_category
        )


# The worked example


@pytest.mark.parametrize(
    "cls_name, expected",
    [
        ("Project", {"project_id", "name", "description", "status", "progress"}),
        ("Team", {"team_id", "project_id", "members"}),
        (
            "Task",
            {"task_id", "project_id", "assignee_id", "title", "status", "comments"},
        ),
        ("TimeEntry", {"entry_id", "task_id", "user_id", "hours", "description"}),
    ],
)
def test_split_aggregates_have_the_fields_the_page_shows(cls_name, expected):
    example = load_example("patterns/design-small-aggregates/008.py")
    with _context(example):
        cls = getattr(example, cls_name)
        assert cls.element_type.name == "AGGREGATE"
        assert set(declared_fields(cls)) == expected
        _no_cross_aggregate_associations(cls)


@pytest.mark.parametrize(
    "cls_name, references",
    [
        ("Team", {"project_id"}),
        ("Task", {"project_id", "assignee_id"}),
        ("TimeEntry", {"task_id", "user_id"}),
    ],
)
def test_split_aggregates_refer_to_each_other_by_identifier(cls_name, references):
    example = load_example("patterns/design-small-aggregates/008.py")
    with _context(example):
        fields = _field_kinds(getattr(example, cls_name))
        for name in references:
            assert fields[name] == "identifier"


def test_project_no_longer_holds_team_tasks_or_time_entries():
    example = load_example("patterns/design-small-aggregates/008.py")
    with _context(example):
        fields = declared_fields(example.Project)
        assert not {"team", "tasks", "time_entries"} & set(fields)


def test_completing_tasks_updates_project_progress():
    example = load_example("patterns/design-small-aggregates/008.py")
    with _context(example):
        domain = example.domain
        project = example.Project(name="Launch")
        domain.repository_for(example.Project).add(project)

        task_repo = domain.repository_for(example.Task)
        tasks = [
            example.Task(project_id=project.project_id, title=f"Task {n}")
            for n in range(4)
        ]
        for task in tasks:
            task_repo.add(task)

        first = task_repo.get(tasks[0].task_id)
        first.complete()
        assert isinstance(first._events[0], example.TaskCompleted)
        assert first._events[0].project_id == project.project_id
        task_repo.add(first)
        assert (
            domain.repository_for(example.Project).get(project.project_id).progress
            == 25.0
        )

        second = task_repo.get(tasks[1].task_id)
        second.complete()
        task_repo.add(second)
        assert (
            domain.repository_for(example.Project).get(project.project_id).progress
            == 50.0
        )


def test_completing_a_completed_task_raises_no_event():
    example = load_example("patterns/design-small-aggregates/008.py")
    with _context(example):
        task = example.Task(project_id="p1", title="Write docs", status="completed")
        task.complete()
        assert task.status == "completed"
        assert task._events == []


def test_progress_is_unchanged_for_a_project_with_no_tasks():
    example = load_example("patterns/design-small-aggregates/008.py")
    with _context(example):
        project = example.Project(name="Empty", progress=10.0)
        project.update_progress(0, 0)
        assert project.progress == 10.0


# Mistake 2: the correct form


def test_correct_order_holds_only_a_customer_identifier():
    example = load_example("patterns/design-small-aggregates/009.py")
    with _context(example):
        fields = _field_kinds(example.Order)
        assert fields["customer_id"] == "identifier"
        assert "customer" not in fields
        _no_cross_aggregate_associations(example.Order)
