import pytest

from protean import Domain

domain = Domain(name="FactoryMethodsOrders")

# --8<-- [start:elements]
from protean import current_domain, handle
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import ValidationError
from protean.fields import (
    Auto,
    Boolean,
    Dict,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
)


@domain.value_object
class Address:
    street: String(required=True)
    city: String(required=True)
    state: String()
    postal_code: String(required=True)
    country: String(default="US")


@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    name: String(required=True)
    quantity: Integer(min_value=1, required=True)
    unit_price: Float(required=True)


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.command(part_of="Order")
class PlaceOrder:
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)
    shipping_address: Dict()


@domain.command(part_of="Order")
class RenewSubscriptionOrder:
    previous_order_id: Identifier(required=True)
    current_prices: Dict()


@domain.command(part_of="Order")
class CreateReplacementOrder:
    original_order_id: Identifier(required=True)
    returned_item_ids: List(content_type=String)


# --8<-- [end:elements]


# --8<-- [start:aggregate]
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    shipping_address = ValueObject(Address)
    status: String(default="draft")
    total: Float(default=0.0)
    is_renewal: Boolean(default=False)

    @classmethod
    def from_cart(
        cls,
        customer_id: str,
        cart_items: list[dict],
        shipping_address: Address,
    ) -> "Order":
        """Create an Order from cart checkout."""
        order = cls(
            customer_id=customer_id,
            shipping_address=shipping_address,
        )

        for item in cart_items:
            order.add_item(
                product_id=item["product_id"],
                name=item["name"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
            )

        order.place()
        return order

    @classmethod
    def from_subscription_renewal(
        cls,
        previous_order: "Order",
        current_prices: dict[str, float],
    ) -> "Order":
        """Create a renewal Order from a previous subscription order."""
        if previous_order.status != "delivered":
            raise ValidationError(
                {"previous_order": ["Can only renew from a delivered order"]}
            )

        order = cls(
            customer_id=previous_order.customer_id,
            shipping_address=previous_order.shipping_address,
            is_renewal=True,
        )

        for item in previous_order.items:
            order.add_item(
                product_id=item.product_id,
                name=item.name,
                quantity=item.quantity,
                unit_price=current_prices[item.product_id],
            )

        order.place()
        return order

    @classmethod
    def as_replacement(
        cls,
        original_order: "Order",
        returned_item_ids: list[str],
    ) -> "Order":
        """Create a replacement Order for returned items."""
        order = cls(
            customer_id=original_order.customer_id,
            shipping_address=original_order.shipping_address,
        )

        for item in original_order.items:
            if item.product_id in returned_item_ids:
                order.add_item(
                    product_id=item.product_id,
                    name=item.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )

        order.place()
        return order

    def add_item(self, product_id, name, quantity, unit_price):
        self.add_items(
            OrderItem(
                product_id=product_id,
                name=name,
                quantity=quantity,
                unit_price=unit_price,
            )
        )
        self._recalculate_total()

    def place(self):
        if not self.items:
            raise ValidationError({"items": ["Order must have at least one item"]})
        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                total=self.total,
            )
        )

    def _recalculate_total(self):
        self.total = sum(item.quantity * item.unit_price for item in self.items)


# --- Handlers become thin ---


@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)
        order = Order.from_cart(
            customer_id=command.customer_id,
            cart_items=command.items,
            shipping_address=Address(**command.shipping_address),
        )
        repo.add(order)

    @handle(RenewSubscriptionOrder)
    def renew_subscription(self, command: RenewSubscriptionOrder):
        repo = current_domain.repository_for(Order)
        previous = repo.get(command.previous_order_id)
        order = Order.from_subscription_renewal(
            previous_order=previous,
            current_prices=command.current_prices,
        )
        repo.add(order)

    @handle(CreateReplacementOrder)
    def create_replacement(self, command: CreateReplacementOrder):
        repo = current_domain.repository_for(Order)
        original = repo.get(command.original_order_id)
        order = Order.as_replacement(
            original_order=original,
            returned_item_ids=command.returned_item_ids,
        )
        repo.add(order)


# --8<-- [end:aggregate]


@domain.entity(part_of="Cart")
class CartLine:
    product_id: Identifier(required=True)
    product_name: String(required=True)
    quantity: Integer(min_value=1, required=True)
    unit_price: Float(required=True)


@domain.aggregate
class Cart:
    items = HasMany(CartLine)


@domain.aggregate
class Customer:
    name: String(required=True)
    is_suspended: Boolean(default=False)
    default_address = ValueObject(Address)


# --8<-- [start:standalone_factory]
# domain/order/factories.py


class OrderFactory:
    """Encapsulates complex Order creation that requires
    loading data from multiple sources."""

    @classmethod
    def from_cart_checkout(
        cls,
        cart_id: str,
        customer_id: str,
    ) -> Order:
        """Create an Order by loading a Cart and Customer."""
        cart = current_domain.repository_for(Cart).get(cart_id)
        customer = current_domain.repository_for(Customer).get(customer_id)

        if customer.is_suspended:
            raise ValidationError(
                {"customer": ["Suspended customers cannot place orders"]}
            )

        if not cart.items:
            raise ValidationError({"cart": ["Cannot create order from empty cart"]})

        order = Order(
            customer_id=customer.id,
            shipping_address=customer.default_address,
        )

        for item in cart.items:
            order.add_item(
                product_id=item.product_id,
                name=item.product_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )

        order.place()
        return order


# --8<-- [end:standalone_factory]


@pytest.fixture
def test_domain():
    domain.init(traverse=False)
    with domain.domain_context():
        yield domain


# --8<-- [start:tests]
class TestOrderCreation:
    def test_from_cart_creates_order_with_items(self, test_domain):
        order = Order.from_cart(
            customer_id="cust-1",
            cart_items=[
                {
                    "product_id": "p1",
                    "name": "Widget",
                    "quantity": 2,
                    "unit_price": 10.0,
                },
                {
                    "product_id": "p2",
                    "name": "Gadget",
                    "quantity": 1,
                    "unit_price": 25.0,
                },
            ],
            shipping_address=Address(
                street="123 Main St",
                city="Springfield",
                state="IL",
                postal_code="62701",
                country="US",
            ),
        )

        assert order.customer_id == "cust-1"
        assert len(order.items) == 2
        assert order.total == 45.0
        assert order.status == "placed"
        assert len(order._events) == 1
        assert isinstance(order._events[0], OrderPlaced)

    def test_renewal_uses_current_prices(self, test_domain):
        previous = Order(
            customer_id="cust-1",
            shipping_address=Address(
                street="123 Main St", city="Springfield", postal_code="62701"
            ),
            status="delivered",
        )
        previous.add_item(product_id="p1", name="Widget", quantity=2, unit_price=10.0)

        renewed = Order.from_subscription_renewal(
            previous_order=previous,
            current_prices={"p1": 12.0},  # Price increased
        )

        assert renewed.items[0].unit_price == 12.0  # Uses current price
        assert renewed.total == 24.0
        assert renewed.is_renewal is True

    def test_replacement_includes_only_returned_items(self, test_domain):
        original = Order(
            customer_id="cust-1",
            shipping_address=Address(
                street="123 Main St", city="Springfield", postal_code="62701"
            ),
        )
        original.add_item(product_id="p1", name="Widget", quantity=1, unit_price=10.0)
        original.add_item(product_id="p2", name="Gadget", quantity=1, unit_price=25.0)

        replacement = Order.as_replacement(
            original_order=original,
            returned_item_ids=["p1"],
        )

        assert len(replacement.items) == 1
        assert replacement.items[0].product_id == "p1"

    def test_renewal_rejects_undelivered_order(self, test_domain):
        previous = Order(customer_id="cust-1", status="draft")

        with pytest.raises(ValidationError) as exc:
            Order.from_subscription_renewal(
                previous_order=previous,
                current_prices={},
            )

        assert "delivered" in str(exc.value)


# --8<-- [end:tests]
