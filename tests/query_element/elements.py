"""Shared test elements for Query domain element tests."""

from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.value_object import BaseValueObject
from protean.fields import Float, Identifier, Integer, String


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    status = String(max_length=20)
    total_amount = Float()


class ProductSearch(BaseProjection):
    product_id = Identifier(identifier=True)
    name = String(max_length=200)
    category = String(max_length=50)


class Money(BaseValueObject):
    amount = Float(required=True)
    currency = String(required=True, max_length=3, default="USD")


class GetOrdersByCustomer(BaseQuery):
    customer_id = Identifier(required=True)
    status = String()
    page = Integer(default=1)
    page_size = Integer(default=20)


class GetOrderById(BaseQuery):
    order_id = Identifier(required=True)
