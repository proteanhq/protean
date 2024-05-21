import pytest

from datetime import date
from enum import Enum

from protean import BaseAggregate, BaseEntity, invariant, atomic_change
from protean.exceptions import ValidationError
from protean.fields import Date, Float, Identifier, Integer, String, HasMany


class OrderStatus(Enum):
    PENDING = "PENDING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class Order(BaseAggregate):
    customer_id = Identifier()
    order_date = Date()
    total_amount = Float()
    status = String(max_length=50, choices=OrderStatus)
    items = HasMany("OrderItem")

    @invariant
    def total_amount_of_order_must_equal_sum_of_subtotal_of_all_items(self):
        if self.total_amount != sum(item.subtotal for item in self.items):
            raise ValidationError({"_entity": ["Total should be sum of item prices"]})

    @invariant
    def order_date_must_be_within_the_last_30_days_if_status_is_pending(self):
        if self.status == OrderStatus.PENDING.value and self.order_date < date(
            2020, 1, 1
        ):
            raise ValidationError(
                {
                    "_entity": [
                        "Order date must be within the last 30 days if status is PENDING"
                    ]
                }
            )

    @invariant
    def customer_id_must_be_non_null_and_the_order_must_contain_at_least_one_item(self):
        if not self.customer_id or not self.items:
            raise ValidationError(
                {
                    "_entity": [
                        "Customer ID must be non-null and the order must contain at least one item"
                    ]
                }
            )


class OrderItem(BaseEntity):
    product_id = Identifier()
    quantity = Integer()
    price = Float()
    subtotal = Float()

    class Meta:
        part_of = Order

    @invariant
    def the_quantity_must_be_a_positive_integer_and_the_subtotal_must_be_correctly_calculated(
        self,
    ):
        if self.quantity <= 0 or self.subtotal != self.quantity * self.price:
            raise ValidationError(
                {
                    "_entity": [
                        "Quantity must be a positive integer and the subtotal must be correctly calculated"
                    ]
                }
            )


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(OrderItem)
    test_domain.register(Order)
    test_domain.init(traverse=False)


class TestEntityInvariantsOnInitialization:
    def test_with_valid_data(self):
        order = Order(
            customer_id="1",
            order_date="2020-01-01",
            total_amount=100.0,
            status="PENDING",
            items=[
                OrderItem(product_id="1", quantity=4, price=10.0, subtotal=40.0),
                OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
            ],
        )
        assert order is not None

    def test_when_total_amount_is_not_sum_of_item_subtotals(self):
        with pytest.raises(ValidationError) as exc:
            Order(
                customer_id="1",
                order_date="2020-01-01",
                total_amount=100.0,
                status="PENDING",
                items=[
                    OrderItem(product_id="1", quantity=2, price=10.0, subtotal=20.0),
                    OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
                ],
            )

        assert exc.value.messages["_entity"] == ["Total should be sum of item prices"]

    def test_when_order_date_is_not_within_the_last_30_days(self):
        with pytest.raises(ValidationError) as exc:
            Order(
                customer_id="1",
                order_date="2019-12-01",
                total_amount=100.0,
                status="PENDING",
                items=[
                    OrderItem(product_id="1", quantity=4, price=10.0, subtotal=40.0),
                    OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
                ],
            )

        assert exc.value.messages["_entity"] == [
            "Order date must be within the last 30 days if status is PENDING"
        ]

    def test_when_customer_ID_is_null(self):
        with pytest.raises(ValidationError) as exc:
            Order(
                customer_id=None,
                order_date="2020-01-01",
                total_amount=100.0,
                status="PENDING",
                items=[
                    OrderItem(product_id="1", quantity=4, price=10.0, subtotal=40.0),
                    OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
                ],
            )

        assert exc.value.messages["_entity"] == [
            "Customer ID must be non-null and the order must contain at least one item"
        ]

    def test_when_items_are_empty(self):
        with pytest.raises(ValidationError) as exc:
            Order(
                customer_id="1",
                order_date="2020-01-01",
                total_amount=100.0,
                status="PENDING",
                items=[],
            )

        assert exc.value.messages["_entity"] == [
            "Customer ID must be non-null and the order must contain at least one item",
            "Total should be sum of item prices",
        ]

    def test_when_quantity_is_negative(self):
        with pytest.raises(ValidationError) as exc:
            Order(
                customer_id="1",
                order_date="2020-01-01",
                total_amount=100.0,
                status="PENDING",
                items=[
                    OrderItem(product_id="1", quantity=-1, price=10.0, subtotal=10.0),
                    OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
                ],
            )

        assert exc.value.messages["_entity"] == [
            "Quantity must be a positive integer and the subtotal must be correctly calculated"
        ]

    def test_when_subtotal_is_incorrect(self):
        with pytest.raises(ValidationError) as exc:
            Order(
                customer_id="1",
                order_date="2020-01-01",
                total_amount=100.0,
                status="PENDING",
                items=[
                    OrderItem(product_id="1", quantity=1, price=10.0, subtotal=20.0),
                    OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
                ],
            )

        assert exc.value.messages["_entity"] == [
            "Quantity must be a positive integer and the subtotal must be correctly calculated"
        ]


@pytest.fixture
def order():
    return Order(
        customer_id="1",
        order_date="2020-01-01",
        total_amount=100.0,
        status="PENDING",
        items=[
            OrderItem(product_id="1", quantity=4, price=10.0, subtotal=40.0),
            OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
        ],
    )


class TestEntityInvariantsOnAttributeChanges:
    def test_when_total_amount_is_not_sum_of_item_subtotals(self, order):
        with pytest.raises(ValidationError) as exc:
            order.total_amount = 50.0

        assert exc.value.messages["_entity"] == ["Total should be sum of item prices"]

    def test_when_order_date_is_not_within_the_last_30_days(self, order):
        with pytest.raises(ValidationError) as exc:
            order.order_date = "2019-12-01"

        assert exc.value.messages["_entity"] == [
            "Order date must be within the last 30 days if status is PENDING"
        ]

    def test_when_customer_ID_is_null(self, order):
        with pytest.raises(ValidationError) as exc:
            order.customer_id = None

        assert exc.value.messages["_entity"] == [
            "Customer ID must be non-null and the order must contain at least one item"
        ]

    def test_when_items_are_empty(self, order):
        with pytest.raises(ValidationError) as exc:
            order.items = []

        assert exc.value.messages["_entity"] == [
            "Customer ID must be non-null and the order must contain at least one item",
            "Total should be sum of item prices",
        ]

    def test_when_invalid_item_is_added(self, order):
        with pytest.raises(ValidationError) as exc:
            order.add_items(
                OrderItem(product_id="3", quantity=2, price=10.0, subtotal=40.0)
            )

        assert exc.value.messages["_entity"] == [
            "Quantity must be a positive integer and the subtotal must be correctly calculated"
        ]

    def test_when_item_is_added_along_with_total_amount(self, order):
        try:
            with atomic_change(order):
                order.total_amount = 120.0
                order.add_items(
                    OrderItem(product_id="3", quantity=2, price=10.0, subtotal=20.0)
                )
        except ValidationError:
            pytest.fail("Failed to batch update attributes")

    def test_when_quantity_is_negative(self, order):
        with pytest.raises(ValidationError) as exc:
            order.items[0].quantity = -1

        assert exc.value.messages["_entity"] == [
            "Quantity must be a positive integer and the subtotal must be correctly calculated"
        ]

    def test_when_invalid_item_is_added_after_initialization(self, order):
        with pytest.raises(ValidationError) as exc:
            order.add_items(
                OrderItem(product_id="3", quantity=2, price=10.0, subtotal=40.0)
            )

        assert exc.value.messages["_entity"] == [
            "Quantity must be a positive integer and the subtotal must be correctly calculated"
        ]

    def test_when_item_price_is_changed_to_negative(self, order):
        with pytest.raises(ValidationError) as exc:
            order.items[0].price = -10.0

        assert exc.value.messages["_entity"] == [
            "Quantity must be a positive integer and the subtotal must be correctly calculated"
        ]
