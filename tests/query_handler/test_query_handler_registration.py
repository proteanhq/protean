"""Tests for QueryHandler registration with the domain."""

import pytest

from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.exceptions import NotSupportedError
from protean.fields import Float, Identifier, String
from protean.utils import DomainObjects
from protean.utils.mixins import read


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total_amount = Float()


class GetOrdersByCustomer(BaseQuery):
    customer_id = Identifier(required=True)


class OrderSummaryQueryHandler(BaseQueryHandler):
    @read(GetOrdersByCustomer)
    def get_by_customer(self, query):
        return []


class TestQueryHandlerRegistration:
    def test_query_handler_can_be_registered_with_decorator(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
        test_domain.init(traverse=False)

        assert DomainObjects.QUERY_HANDLER.value in test_domain.registry._elements

    def test_query_handler_appears_in_registry(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
        test_domain.init(traverse=False)

        assert len(test_domain.registry.query_handlers) == 1

    def test_query_handler_element_type(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
        test_domain.init(traverse=False)

        assert OrderSummaryQueryHandler.element_type == DomainObjects.QUERY_HANDLER

    def test_base_query_handler_cannot_be_instantiated(self):
        with pytest.raises(
            NotSupportedError, match="BaseQueryHandler cannot be instantiated"
        ):
            BaseQueryHandler()

    def test_query_handler_registered_via_domain_decorator(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)

        @test_domain.query_handler(part_of=OrderSummary)
        class MyQueryHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def get_by_customer(self, query):
                return []

        test_domain.init(traverse=False)

        assert len(test_domain.registry.query_handlers) == 1
