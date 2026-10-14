"""Run the examples on ``docs/patterns/validation-layering.md``."""

from datetime import UTC, date, datetime, timedelta

import pytest

from protean.exceptions import ObjectNotFoundError, ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

ITEMS = [{"product_id": "prod-1", "quantity": 2, "unit_price": 29.99}]
VALID_COMMAND = {
    "order_id": "ord-123",
    "customer_id": "cust-456",
    "items": ITEMS,
    "total": 59.98,
    "currency": "USD",
}

# One place-order input per layer of the "Layers in Action" flow. Each input
# breaks only the rule its layer owns. ``suspended`` is the customer's credit
# status, the state the handler guard reads.
LAYER_INPUTS = {
    "field": {
        "command": {k: v for k, v in VALID_COMMAND.items() if k != "customer_id"},
        "suspended": False,
    },
    "value_object": {
        "command": {**VALID_COMMAND, "currency": "XYZ"},
        "suspended": False,
    },
    "aggregate": {
        "command": {**VALID_COMMAND, "total": 50.0},
        "suspended": False,
    },
    "guard": {"command": VALID_COMMAND, "suspended": True},
}

# The error each layer raises for the input it owns.
LAYER_ERRORS = {
    "field": {"customer_id": ["is required"]},
    "value_object": {"currency": ["Invalid currency: XYZ"]},
    "aggregate": {"total": ["Total 50.0 does not match items total 59.98"]},
    "guard": {"credit": ["Customer credit is suspended"]},
}


@pytest.fixture
def problem():
    example = load_example("patterns/validation-layering/001.py")
    with example.domain.domain_context():
        yield example


@pytest.fixture
def fields():
    example = load_example("patterns/validation-layering/002.py")
    with example.domain.domain_context():
        yield example


@pytest.fixture
def layers():
    example = load_example("patterns/validation-layering/003.py")
    with example.domain.domain_context():
        yield example


@pytest.fixture
def policy():
    example = load_example("patterns/validation-layering/004.py")
    with example.domain.domain_context():
        yield example


# --- The Problem ---


@pytest.mark.parametrize(
    ("email", "role", "message"),
    [
        ("bad-email", "member", "Invalid email format"),
        ("boss@gmail.com", "admin", "Admins must use a company email address"),
    ],
)
def test_problem_user_invariants_reject(problem, email, role, message):
    with pytest.raises(ValidationError) as exc:
        problem.User(email=email, role=role)

    assert exc.value.messages["email"] == [message]


@pytest.mark.parametrize(
    ("email", "role"),
    [("someone@gmail.com", "member"), ("boss@company.com", "admin")],
)
def test_problem_user_accepts_valid_input(problem, email, role):
    assert problem.User(email=email, role=role).email == email


# --- Layer 1: Field Constraints ---

VALID_PRODUCT = {"name": "Widget", "sku": "WG-0001", "price": 10.0}


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"name": None}, "name"),
        ({"name": "x" * 201}, "name"),
        ({"price": -5.0}, "price"),
        ({"status": "invalid"}, "status"),
        ({"stock_count": "abc"}, "stock_count"),
    ],
)
def test_field_constraints_reject_bad_values(fields, change, field):
    with pytest.raises(ValidationError) as exc:
        fields.Product(**{**VALID_PRODUCT, **change})

    assert list(exc.value.messages) == [field]


def test_field_constraints_accept_values_in_range(fields):
    product = fields.Product(
        **{**VALID_PRODUCT, "name": "x" * 200}, weight_kg=0.0, status="active"
    )

    assert product.price == 10.0
    assert product.stock_count == 0
    assert product.status == "active"


# --- Layer 2: Value Object Invariants ---


def test_value_object_invariants_reject_invalid_concepts(layers):
    today = date(2026, 10, 14)
    cases = [
        (lambda: layers.Email(address="not-an-email"), "address"),
        (lambda: layers.Email(address="a@localhost"), "address"),
        (lambda: layers.Money(amount=-5, currency="USD"), "amount"),
        (lambda: layers.Money(amount=10, currency="XYZ"), "currency"),
        (
            lambda: layers.DateRange(
                start_date=today, end_date=today - timedelta(days=1)
            ),
            "end_date",
        ),
    ]
    assert cases
    for build, field in cases:
        with pytest.raises(ValidationError) as exc:
            build()
        assert list(exc.value.messages) == [field]


def test_value_objects_accept_valid_concepts(layers):
    today = date(2026, 10, 14)

    assert layers.Email(address="ana@example.com").address == "ana@example.com"
    assert layers.Money(amount=0, currency="EUR").amount == 0
    period = layers.DateRange(start_date=today, end_date=today + timedelta(days=1))
    assert period.end_date > period.start_date


# --- Layer 3: Aggregate Invariants ---


def order_items(layers, items=ITEMS):
    return [layers.OrderItem(**item) for item in items]


def test_order_cannot_be_placed_without_items(layers):
    order = layers.Order(customer_id="cust-1")

    with pytest.raises(ValidationError) as exc:
        order.place()

    assert exc.value.messages["items"] == ["Order must have at least one item"]


def test_discount_cannot_exceed_total(layers):
    with pytest.raises(ValidationError) as exc:
        layers.Order(
            customer_id="cust-1",
            total=layers.Money(amount=5, currency="USD"),
            discount=layers.Money(amount=6, currency="USD"),
        )

    assert exc.value.messages["discount"] == ["Discount cannot exceed order total"]


def test_total_must_match_items(layers):
    with pytest.raises(ValidationError) as exc:
        layers.Order(
            customer_id="cust-1",
            items=order_items(layers),
            total=layers.Money(amount=50.0, currency="USD"),
        )

    assert exc.value.messages["total"] == [
        "Total 50.0 does not match items total 59.98"
    ]


def test_only_draft_orders_can_be_placed(layers):
    order = layers.Order(
        customer_id="cust-1",
        items=order_items(layers),
        total=layers.Money(amount=59.98, currency="USD"),
        status="cancelled",
    )

    with pytest.raises(ValidationError) as exc:
        order.place()

    assert exc.value.messages["status"] == ["Only draft orders can be placed"]


def test_consistent_order_is_placed(layers):
    order = layers.Order(
        customer_id="cust-1",
        items=order_items(layers),
        total=layers.Money(amount=59.98, currency="USD"),
        discount=layers.Money(amount=5, currency="USD"),
    )

    order.place()

    assert order.status == "placed"
    assert order.placed_at is not None


# --- Layer 4: Handler and Service Guards ---


def stored_order(layers, placed_at):
    order = layers.Order(
        customer_id="cust-1",
        items=order_items(layers),
        total=layers.Money(amount=59.98, currency="USD"),
        status="placed",
        placed_at=placed_at,
    )
    layers.domain.repository_for(layers.Order).add(order)
    return order


def cancel(layers, order, by, role):
    layers.domain.process(
        layers.CancelOrder(
            order_id=order.order_id,
            cancelled_by=by,
            cancelled_by_role=role,
            reason="changed mind",
        ),
        asynchronous=False,
    )
    return layers.domain.repository_for(layers.Order).get(order.order_id)


@pytest.mark.parametrize(
    ("by", "role", "hours_ago", "key"),
    [
        ("someone-else", "member", 1, "authorization"),
        ("cust-1", "member", 25, "timing"),
        ("admin-1", "admin", 25, "timing"),
    ],
)
def test_cancel_guards_reject(layers, by, role, hours_ago, key):
    order = stored_order(layers, datetime.now(UTC) - timedelta(hours=hours_ago))

    with pytest.raises(ValidationError) as exc:
        cancel(layers, order, by, role)

    assert list(exc.value.messages) == [key]
    repo = layers.domain.repository_for(layers.Order)
    assert repo.get(order.order_id).status == "placed"


@pytest.mark.parametrize(("by", "role"), [("cust-1", "member"), ("admin-1", "admin")])
def test_cancel_guards_accept_the_customer_or_an_admin_within_24_hours(
    layers, by, role
):
    order = stored_order(layers, datetime.now(UTC) - timedelta(hours=1))

    cancelled = cancel(layers, order, by, role)

    assert cancelled.status == "cancelled"
    assert cancelled.cancellation_reason == "changed mind"


@pytest.mark.parametrize(
    ("frozen", "amount", "messages"),
    [
        (False, 600.0, {"amount": ["Transfer exceeds policy limit of 500.0"]}),
        (True, 100.0, {"account": ["Source account is frozen"]}),
    ],
)
def test_transfer_service_rejects(layers, frozen, amount, messages):
    source = layers.Account(balance=1000.0, is_frozen=frozen)
    limit = layers.CreditPolicy(max_single_transfer=500.0)

    with pytest.raises(ValidationError) as exc:
        layers.TransferValidationService.validate_transfer(source, limit, amount)

    assert exc.value.messages == messages


def test_transfer_service_accepts_a_transfer_within_policy(layers):
    source = layers.Account(balance=1000.0)
    limit = layers.CreditPolicy(max_single_transfer=500.0)

    assert (
        layers.TransferValidationService.validate_transfer(source, limit, 500.0) is None
    )


# --- The Layers in Action: each layer owns its own input ---


def seed_credit(layers, suspended):
    layers.domain.repository_for(layers.CustomerCredit).add(
        layers.CustomerCredit(customer_id="cust-456", is_suspended=suspended)
    )


def check_field(layers, case):
    layers.PlaceOrder(**case["command"])


def check_value_object(layers, case):
    layers.Money(amount=case["command"]["total"], currency=case["command"]["currency"])


def check_aggregate(layers, case):
    # The aggregate gets a valid Money and a customer: the currency is the value
    # object's concern, and a missing customer_id is the command's.
    command = case["command"]
    layers.Order(
        customer_id=command.get("customer_id", "cust-456"),
        items=order_items(layers, command["items"]),
        total=layers.Money(amount=command["total"], currency="USD"),
    ).place()


def check_guard(layers, case):
    # The guard is the first step of the handler. An error from a later step
    # means the guard let the input through.
    seed_credit(layers, case["suspended"])
    try:
        layers.domain.process(layers.PlaceOrder(**case["command"]), asynchronous=False)
    except ValidationError as exc:
        if "credit" in exc.messages:
            raise


LAYER_CHECKS = {
    "field": check_field,
    "value_object": check_value_object,
    "aggregate": check_aggregate,
    "guard": check_guard,
}

# The guard can not be asked about an input the command refuses to build.
UNREACHABLE = {("guard", "field")}

OTHER_LAYER_PAIRS = [
    (layer, owner)
    for layer in LAYER_CHECKS
    for owner in LAYER_INPUTS
    if layer != owner and (layer, owner) not in UNREACHABLE
]


@pytest.mark.parametrize("layer", list(LAYER_CHECKS))
def test_layer_rejects_the_input_it_owns(layers, layer):
    with pytest.raises(ValidationError) as exc:
        LAYER_CHECKS[layer](layers, LAYER_INPUTS[layer])

    assert exc.value.messages == LAYER_ERRORS[layer]


@pytest.mark.parametrize(("layer", "owner"), OTHER_LAYER_PAIRS)
def test_layer_accepts_input_another_layer_owns(layers, layer, owner):
    LAYER_CHECKS[layer](layers, LAYER_INPUTS[owner])


def test_every_layer_has_an_input_and_is_checked_against_the_others():
    assert set(LAYER_INPUTS) == set(LAYER_CHECKS) == set(LAYER_ERRORS)
    assert len(OTHER_LAYER_PAIRS) == 4 * 3 - len(UNREACHABLE)


@pytest.mark.parametrize("layer", ["guard", "value_object", "aggregate"])
def test_place_order_flow_stops_at_the_owning_layer(layers, layer):
    # Getting exactly the owner's error shows every earlier layer accepted the
    # input. The order of the layers is checked separately below.
    case = LAYER_INPUTS[layer]
    seed_credit(layers, case["suspended"])

    with pytest.raises(ValidationError) as exc:
        layers.domain.process(layers.PlaceOrder(**case["command"]), asynchronous=False)

    assert exc.value.messages == LAYER_ERRORS[layer]
    with pytest.raises(ObjectNotFoundError):
        layers.domain.repository_for(layers.Order).get("ord-123")


@pytest.mark.parametrize(
    ("command", "suspended", "first"),
    [
        ({**VALID_COMMAND, "currency": "XYZ"}, True, "guard"),
        ({**VALID_COMMAND, "currency": "XYZ", "total": 50.0}, False, "value_object"),
    ],
)
def test_place_order_flow_runs_the_guard_then_the_value_object_then_the_aggregate(
    layers, command, suspended, first
):
    seed_credit(layers, suspended)

    with pytest.raises(ValidationError) as exc:
        layers.domain.process(layers.PlaceOrder(**command), asynchronous=False)

    assert exc.value.messages == LAYER_ERRORS[first]


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"total": -1.0}, "total"),
        ({"currency": "USDX"}, "currency"),
    ],
)
def test_place_order_command_rejects_bad_field_values(layers, change, field):
    with pytest.raises(ValidationError) as exc:
        layers.PlaceOrder(**{**VALID_COMMAND, **change})

    assert list(exc.value.messages) == [field]


def test_submit_order_passes_every_layer(layers):
    seed_credit(layers, False)

    layers.submit_order()

    order = layers.domain.repository_for(layers.Order).get("ord-123")
    assert order.status == "placed"
    assert order.total.amount == 59.98
    assert [(i.product_id, i.quantity) for i in order.items] == [("prod-1", 2)]


# --- Anti-patterns: the discount policy as an invariant ---


@pytest.mark.parametrize(
    ("percent", "message"),
    [
        (60.0, "Discount cannot exceed 50%"),
        (150.0, None),
    ],
)
def test_discount_policy_rejects(policy, percent, message):
    with pytest.raises(ValidationError) as exc:
        policy.Order(discount_percent=percent)

    errors = exc.value.messages["discount_percent"]
    if message:
        assert errors == [message]
    else:
        # Above 100% fails the field's physical range, not the policy.
        assert "Discount cannot exceed 50%" not in errors


@pytest.mark.parametrize("percent", [0.0, 50.0])
def test_discount_policy_accepts_discounts_up_to_50_percent(policy, percent):
    assert policy.Order(discount_percent=percent).discount_percent == percent
