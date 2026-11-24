"""Tests verifying that a query cannot be handled by multiple handlers."""

import pytest

from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import Float, Identifier, String
from protean.utils.mixins import read


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total_amount = Float()


class GetOrdersByCustomer(BaseQuery):
    customer_id = Identifier(required=True)


class TestMultipleHandlersDisallowed:
    def test_two_methods_for_same_query_in_one_handler(self, test_domain):
        """Two methods in the same handler targeting the same query should raise."""
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)

        class DuplicateHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def method_one(self, query):
                return []

            @read(GetOrdersByCustomer)
            def method_two(self, query):
                return []

        test_domain.register(DuplicateHandler, part_of=OrderSummary)

        with pytest.raises(
            NotSupportedError,
            match="cannot be handled by multiple handlers",
        ):
            test_domain.init(traverse=False)

    def test_two_handler_classes_for_same_query(self, test_domain):
        """Two handler classes reading the same query should fail init."""
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)

        class FirstHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def by_customer(self, query):
                return []

        class SecondHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def by_customer(self, query):
                return []

        test_domain.register(FirstHandler, part_of=OrderSummary)
        test_domain.register(SecondHandler, part_of=OrderSummary)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert exc.value.args[0] == (
            "Queries cannot be handled by multiple handlers: "
            f"{GetOrdersByCustomer.__type__}"
        )

    def test_check_reports_two_handler_classes_for_same_query(self, test_domain):
        """`domain.check()` reports the cross-class collision as one error."""
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)

        class FirstHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def by_customer(self, query):
                return []

        class SecondHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def by_customer(self, query):
                return []

        test_domain.register(FirstHandler, part_of=OrderSummary)
        test_domain.register(SecondHandler, part_of=OrderSummary)

        report = test_domain.check(traverse=False)

        assert report["status"] == "fail"
        assert report["errors"] == [
            {
                "code": "IncorrectUsageError",
                "element": "_validate_unique_query_handlers",
                "level": "error",
                "message": (
                    "Queries cannot be handled by multiple handlers: "
                    f"{GetOrdersByCustomer.__type__}"
                ),
            }
        ]

    def test_message_lists_every_duplicated_query_sorted(self, test_domain):
        """The message names each duplicated query once, in sorted order."""

        class ZListOrders(BaseQuery):
            customer_id = Identifier(required=True)

        class AGetOrder(BaseQuery):
            order_id = Identifier(required=True)

        test_domain.register(OrderSummary)
        # The handlers read ZListOrders first, so only sorting puts AGetOrder first.
        test_domain.register(ZListOrders, part_of=OrderSummary)
        test_domain.register(AGetOrder, part_of=OrderSummary)

        class FirstHandler(BaseQueryHandler):
            @read(ZListOrders)
            def fetch_orders(self, query):
                return []

            @read(AGetOrder)
            def get_order(self, query):
                return None

        class SecondHandler(BaseQueryHandler):
            @read(ZListOrders)
            def fetch_orders(self, query):
                return []

            @read(AGetOrder)
            def get_order(self, query):
                return None

        class ThirdHandler(BaseQueryHandler):
            @read(ZListOrders)
            def fetch_orders(self, query):
                return []

        test_domain.register(FirstHandler, part_of=OrderSummary)
        test_domain.register(SecondHandler, part_of=OrderSummary)
        test_domain.register(ThirdHandler, part_of=OrderSummary)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert exc.value.args[0] == (
            "Queries cannot be handled by multiple handlers: "
            f"{AGetOrder.__type__}, {ZListOrders.__type__}"
        )

    def test_handler_classes_for_different_queries_pass_init(self, test_domain):
        """Two handler classes on one projection reading different queries are valid."""

        class GetOrderById(BaseQuery):
            order_id = Identifier(required=True)

        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.register(GetOrderById, part_of=OrderSummary)

        class CustomerHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def by_customer(self, query):
                return []

        class OrderHandler(BaseQueryHandler):
            @read(GetOrderById)
            def by_id(self, query):
                return None

        test_domain.register(CustomerHandler, part_of=OrderSummary)
        test_domain.register(OrderHandler, part_of=OrderSummary)

        test_domain.init(traverse=False)

        assert test_domain.check(traverse=False)["errors"] == []

    def test_lookup_for_an_unread_query_is_not_a_duplicate(self, test_domain):
        """A handler lookup for a query the class does not read adds no handler.

        ``_handlers`` is a ``defaultdict``, so the lookup leaves an empty set
        under the query type; the check must not count that as a second handler.
        """

        class GetOrderById(BaseQuery):
            order_id = Identifier(required=True)

        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.register(GetOrderById, part_of=OrderSummary)

        class CustomerHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def by_customer(self, query):
                return []

        class OrderHandler(BaseQueryHandler):
            @read(GetOrderById)
            def by_id(self, query):
                return None

        test_domain.register(CustomerHandler, part_of=OrderSummary)
        test_domain.register(OrderHandler, part_of=OrderSummary)
        test_domain.init(traverse=False)

        # A missing key reads as an empty set and leaves it behind.
        assert not OrderHandler._handlers[GetOrdersByCustomer.__type__]
        assert GetOrdersByCustomer.__type__ in OrderHandler._handlers

        assert test_domain.check(traverse=False)["errors"] == []
