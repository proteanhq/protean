"""Shared test elements for Query Handler tests."""

from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.fields import Float, Identifier, Integer, String
from protean.utils.mixins import read


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    status = String(max_length=20)
    total_amount = Float()


class ProductCatalog(BaseProjection):
    product_id = Identifier(identifier=True)
    name = String(max_length=200)
    category = String(max_length=50)


class GetOrdersByCustomer(BaseQuery):
    customer_id = Identifier(required=True)
    status = String()
    page = Integer(default=1)
    page_size = Integer(default=20)


class GetOrderById(BaseQuery):
    order_id = Identifier(required=True)


class SearchProducts(BaseQuery):
    keyword = String(required=True)
    category = String()


class OrderSummaryQueryHandler(BaseQueryHandler):
    @read(GetOrdersByCustomer)
    def get_by_customer(self, query):
        return [
            {
                "order_id": "order-1",
                "customer_id": query.customer_id,
                "status": "shipped",
            },
            {
                "order_id": "order-2",
                "customer_id": query.customer_id,
                "status": "pending",
            },
        ]

    @read(GetOrderById)
    def get_by_id(self, query):
        return {"order_id": query.order_id, "status": "shipped"}
