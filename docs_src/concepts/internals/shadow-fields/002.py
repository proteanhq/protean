from protean import Domain
from protean.fields import String

domain = Domain(name="ShadowFieldsRenamed")


@domain.aggregate
class Order:
    placed_by: String(max_length=100)


# isort: split

# --8<-- [start:reference_referenced_as]
from protean.fields import Reference, String


@domain.entity(part_of="Order")
class LineItem:
    description: String(max_length=200)
    order = Reference("Order", referenced_as="order_number")


# --8<-- [end:reference_referenced_as]

# --8<-- [start:value_object_referenced_as]
from protean.core.value_object import BaseValueObject
from protean.fields import String, ValueObject


class SupplierAddress(BaseValueObject):
    street: String(max_length=200, referenced_as="addr_street")
    city: String(max_length=100, referenced_as="addr_city")


@domain.aggregate
class Supplier:
    name: String(max_length=100, required=True)
    billing_address: ValueObject(SupplierAddress)


# --8<-- [end:value_object_referenced_as]

domain.init(traverse=False)
