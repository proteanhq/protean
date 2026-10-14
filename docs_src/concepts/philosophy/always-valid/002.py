# --8<-- [start:money]
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, String

domain = Domain(name="AlwaysValidValueObjects")


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(required=True, max_length=3)

    @invariant.post
    def amount_must_be_non_negative(self):
        if self.amount < 0:
            raise ValidationError({"amount": ["Amount cannot be negative"]})

    @invariant.post
    def currency_must_be_recognized(self):
        valid = {"USD", "EUR", "GBP", "JPY", "CAD"}
        if self.currency not in valid:
            raise ValidationError(
                {"currency": [f"Unrecognized currency: {self.currency}"]}
            )


# --8<-- [end:money]


# --8<-- [start:order]
from protean.fields import HasMany, Identifier, Integer, ValueObject


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    total = ValueObject(Money)
    items = HasMany("OrderItem")


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.01)


# --8<-- [end:order]


# --8<-- [start:money_checks]
def show_money_checks():
    # Invalid at construction → ValidationError
    try:
        Money(amount=-5, currency="USD")
    except ValidationError as exc:
        print(exc.messages)  # {'amount': ['Amount cannot be negative']}

    try:
        Money(amount=10, currency="XYZ")
    except ValidationError as exc:
        print(exc.messages)  # {'currency': ['Unrecognized currency: XYZ']}

    # When assigned to an aggregate, the VO validates itself
    order = Order(customer_id="cust-1")
    try:
        order.total = Money(amount=50, currency="FAKE")
    except ValidationError as exc:
        print(exc.messages)  # {'currency': ['String should have at most 3 characters']}


# --8<-- [end:money_checks]
