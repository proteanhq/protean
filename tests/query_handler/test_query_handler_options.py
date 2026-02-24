"""Tests for QueryHandler options and validation."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.exceptions import IncorrectUsageError
from protean.fields import Float, Identifier, String
from protean.utils.mixins import read


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total_amount = Float()


class ProductCatalog(BaseProjection):
    product_id = Identifier(identifier=True)
    name = String(max_length=200)


class GetOrdersByCustomer(BaseQuery):
    customer_id = Identifier(required=True)


class SearchProducts(BaseQuery):
    keyword = String(required=True)


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)


class TestPartOfValidation:
    def test_part_of_is_required(self, test_domain):
        with pytest.raises(
            IncorrectUsageError,
            match="needs to be associated with a Projection",
        ):
            test_domain.register(OrderSummary)

            class NoPartOfHandler(BaseQueryHandler):
                @read(GetOrdersByCustomer)
                def get_by_customer(self, query):
                    return []

            test_domain.register(NoPartOfHandler)

    def test_part_of_must_be_a_projection(self, test_domain):
        """Query handler's part_of must reference a Projection, not an Aggregate."""
        test_domain.register(Order)
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)

        class WrongPartOfHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def get_by_customer(self, query):
                return []

        # The factory doesn't validate the type of part_of,
        # but _validate_domain will catch it
        test_domain.register(WrongPartOfHandler, part_of=Order)

        with pytest.raises(IncorrectUsageError):
            test_domain.init(traverse=False)

    def test_string_part_of_resolves_to_projection(self, test_domain):
        """String part_of should be resolved during init."""
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)

        class StringPartOfHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def get_by_customer(self, query):
                return []

        test_domain.register(StringPartOfHandler, part_of="OrderSummary")
        test_domain.init(traverse=False)

        assert StringPartOfHandler.meta_.part_of == OrderSummary


class TestQueryProjectionMismatch:
    def test_query_projection_must_match_handler_projection(self, test_domain):
        """Query's part_of must match handler's part_of."""
        test_domain.register(OrderSummary)
        test_domain.register(ProductCatalog)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.register(SearchProducts, part_of=ProductCatalog)

        class MismatchedHandler(BaseQueryHandler):
            # SearchProducts is part_of ProductCatalog,
            # but this handler is part_of OrderSummary
            @read(SearchProducts)
            def search(self, query):
                return []

        test_domain.register(MismatchedHandler, part_of=OrderSummary)

        with pytest.raises(
            IncorrectUsageError,
            match="is not associated with the same projection",
        ):
            test_domain.init(traverse=False)


class TestValidateDomainCatchesUnregisteredProjection:
    def test_query_handler_with_unregistered_projection(self, test_domain):
        """_validate_domain should catch query handlers whose part_of projection
        is not registered in the domain."""
        from protean.utils import DomainObjects, fqn

        class GhostProjection(BaseProjection):
            item_id = Identifier(identifier=True)
            name = String(max_length=100)

        # A handler with no @read methods — survives _setup_query_handlers
        class EmptyHandler(BaseQueryHandler):
            pass

        # Register both, then remove the projection before init()
        test_domain.register(GhostProjection)
        test_domain.register(EmptyHandler, part_of=GhostProjection)

        del test_domain.registry._elements[DomainObjects.PROJECTION.value][
            fqn(GhostProjection)
        ]

        with pytest.raises(
            IncorrectUsageError,
            match="is not a Projection, or is not registered",
        ):
            test_domain.init(traverse=False)


class TestHandlerMethodValidation:
    def test_read_target_must_be_a_query(self, test_domain):
        """Methods decorated with @read must target a BaseQuery subclass."""
        test_domain.register(OrderSummary)

        class NotAQuery:
            pass

        class BadTargetHandler(BaseQueryHandler):
            @read(NotAQuery)
            def bad_method(self, query):
                return []

        test_domain.register(BadTargetHandler, part_of=OrderSummary)

        with pytest.raises(
            IncorrectUsageError,
            match="is not associated with a query",
        ):
            test_domain.init(traverse=False)

    def test_query_must_have_part_of(self, test_domain):
        """Query used in @read must have part_of set."""
        test_domain.register(OrderSummary)

        class OrphanQuery(BaseQuery):
            """Abstract query with no part_of."""

            value = String()

        # Register as abstract so factory doesn't fail
        test_domain.register(OrphanQuery, abstract=True)

        class BadHandler(BaseQueryHandler):
            @read(OrphanQuery)
            def handle(self, query):
                return []

        test_domain.register(BadHandler, part_of=OrderSummary)

        with pytest.raises(
            IncorrectUsageError,
            match="is not associated with a projection",
        ):
            test_domain.init(traverse=False)
