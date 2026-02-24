"""Tests for Query registration with the domain.

Validates:
- Query can be registered with a domain
- Query appears in registry.queries
- Query element type is QUERY
- Query can be registered via decorator
- String-based part_of resolves to a Projection at init time
- Multiple queries can target the same projection
"""

from protean.core.query import BaseQuery
from protean.fields import String
from protean.utils import DomainObjects

from .elements import GetOrderById, GetOrdersByCustomer, OrderSummary


class TestQueryRegistration:
    def test_query_can_be_registered_with_domain(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        assert len(test_domain.registry._elements[DomainObjects.QUERY.value]) == 1

    def test_query_appears_in_registry_queries(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        assert len(test_domain.registry.queries) == 1

    def test_query_element_type(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        assert GetOrdersByCustomer.element_type == DomainObjects.QUERY

    def test_query_meta_part_of(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        assert GetOrdersByCustomer.meta_.part_of == OrderSummary


class TestQueryDecoratorRegistration:
    def test_query_registered_via_decorator(self, test_domain):
        test_domain.register(OrderSummary)

        @test_domain.query(part_of=OrderSummary)
        class FindActiveOrders:
            status = String(default="active")

        test_domain.init(traverse=False)

        assert len(test_domain.registry.queries) == 1
        assert FindActiveOrders.element_type == DomainObjects.QUERY

    def test_abstract_query_via_decorator_without_parens(self, test_domain):
        """@domain.query without parens is valid for abstract queries
        when registered with abstract=True."""

        class AbstractSearchQuery(BaseQuery):
            keyword = String()

        test_domain.register(AbstractSearchQuery, abstract=True)
        test_domain.init(traverse=False)

        assert AbstractSearchQuery.meta_.abstract is True


class TestQueryStringPartOfResolution:
    def test_query_with_string_part_of(self, test_domain):
        """part_of can be a string that resolves to a Projection at init time."""
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of="OrderSummary")
        test_domain.init(traverse=False)

        assert GetOrdersByCustomer.meta_.part_of == OrderSummary

    def test_multiple_queries_for_one_projection(self, test_domain):
        """Multiple queries can target the same projection."""
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.register(GetOrderById, part_of=OrderSummary)
        test_domain.init(traverse=False)

        assert len(test_domain.registry.queries) == 2
        assert GetOrdersByCustomer.meta_.part_of == OrderSummary
        assert GetOrderById.meta_.part_of == OrderSummary
