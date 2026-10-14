# --8<-- [start:value_object]
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, String, ValueObject

domain = Domain(name="ReferenceDataEnumeration")


@domain.value_object
class OrderStatus:
    code: String(required=True)
    label: String(required=True)

    @invariant.post
    def code_must_be_known(self):
        if self.code not in _ORDER_STATUSES:
            raise ValidationError({"code": [f"Unknown order status: {self.code}"]})

    @classmethod
    def of(cls, code: str) -> "OrderStatus":
        return cls(code=code, label=_ORDER_STATUSES[code])

    @classmethod
    def all(cls) -> list["OrderStatus"]:
        return [cls(code=code, label=label) for code, label in _ORDER_STATUSES.items()]


_ORDER_STATUSES = {
    "draft": "Draft",
    "placed": "Placed",
    "shipped": "Shipped",
    "delivered": "Delivered",
}
# --8<-- [end:value_object]


# --8<-- [start:aggregate]
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    status = ValueObject(OrderStatus)


def valid_order() -> Order:
    return Order(status=OrderStatus.of("placed"))


def invalid_order() -> Order:
    # Raises ValidationError at construction, no database round-trip
    return Order(status=OrderStatus(code="teleported", label="?"))


# --8<-- [end:aggregate]

domain.init(traverse=False)
