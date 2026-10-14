from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, Float, String, ValueObject

domain = Domain(name="MoneyValueObject")


# --8<-- [start:money]
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, required=True)

    @invariant.post
    def amount_must_be_non_negative(self):
        if self.amount < 0:
            raise ValidationError({"amount": ["Amount cannot be negative"]})

    @invariant.post
    def currency_must_be_valid(self):
        valid_currencies = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD"}
        if self.currency not in valid_currencies:
            raise ValidationError(
                {"currency": [f"Currency must be one of {valid_currencies}"]}
            )

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValidationError({"currency": ["Cannot add different currencies"]})
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def subtract(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValidationError(
                {"currency": ["Cannot subtract different currencies"]}
            )
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def multiply(self, factor: float) -> "Money":
        return Money(amount=self.amount * factor, currency=self.currency)


@domain.aggregate
class Product:
    product_id: Auto(identifier=True)
    name: String(required=True)
    price = ValueObject(Money, required=True)
    cost = ValueObject(Money, required=True)

    def margin(self) -> Money:
        return self.price.subtract(self.cost)


# --8<-- [end:money]


# --8<-- [start:usage]
def widget_margin():
    product = Product(
        name="Widget",
        price=Money(amount=29.99, currency="USD"),
        cost=Money(amount=12.50, currency="USD"),
    )

    margin = product.margin()  # Money(amount=17.49..., currency="USD")
    return margin


def mixed_currency_margin():
    # This raises ValidationError: "Cannot subtract different currencies"
    bad_product = Product(
        name="Widget",
        price=Money(amount=29.99, currency="USD"),
        cost=Money(amount=12.50, currency="EUR"),
    )
    bad_product.margin()


# --8<-- [end:usage]


# --8<-- [start:equality]
money1 = Money(amount=100.0, currency="USD")
money2 = Money(amount=100.0, currency="USD")

assert money1 == money2  # True: same attributes, same value object
# --8<-- [end:equality]

domain.init(traverse=False)
