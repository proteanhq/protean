"""Tests for BaseQuery basic behavior.

Validates:
- Query creation with fields
- Default values applied correctly
- Required field validation
- Immutability after construction
- Serialization (to_dict, payload)
- Equality and hashing
- Template dict pattern
- Extra fields rejected
- No metadata, no __type__, no aggregate_cluster
"""

import pytest

from protean.exceptions import IncorrectUsageError, ValidationError

from .elements import GetOrdersByCustomer, OrderSummary


class TestQueryCreation:
    def test_create_query_with_fields(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetOrdersByCustomer(customer_id="C-123", status="pending")
        assert q.customer_id == "C-123"
        assert q.status == "pending"
        assert q.page == 1
        assert q.page_size == 20

    def test_defaults_applied(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetOrdersByCustomer(customer_id="C-123")
        assert q.page == 1
        assert q.page_size == 20
        assert q.status is None

    def test_required_field_missing_raises(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        with pytest.raises(ValidationError):
            GetOrdersByCustomer()

    def test_extra_fields_rejected(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        with pytest.raises(ValidationError):
            GetOrdersByCustomer(customer_id="C-123", unknown_field="bad")


class TestQueryImmutability:
    def test_query_is_immutable(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetOrdersByCustomer(customer_id="C-123")
        with pytest.raises(IncorrectUsageError, match="immutable"):
            q.customer_id = "C-456"


class TestQuerySerialization:
    def test_to_dict(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetOrdersByCustomer(customer_id="C-123", status="pending")
        d = q.to_dict()
        assert d == {
            "customer_id": "C-123",
            "status": "pending",
            "page": 1,
            "page_size": 20,
        }

    def test_payload_property(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetOrdersByCustomer(customer_id="C-123")
        assert q.payload["customer_id"] == "C-123"
        assert q.payload["page"] == 1

    def test_to_dict_returns_copy(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetOrdersByCustomer(customer_id="C-123")
        d1 = q.to_dict()
        d2 = q.to_dict()
        assert d1 is not d2
        assert d1 == d2


class TestQueryEquality:
    def test_queries_with_same_data_are_equal(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q1 = GetOrdersByCustomer(customer_id="C-123", status="pending")
        q2 = GetOrdersByCustomer(customer_id="C-123", status="pending")
        assert q1 == q2

    def test_queries_with_different_data_are_not_equal(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q1 = GetOrdersByCustomer(customer_id="C-123")
        q2 = GetOrdersByCustomer(customer_id="C-456")
        assert q1 != q2

    def test_query_not_equal_to_different_type(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetOrdersByCustomer(customer_id="C-123")
        assert q != "not a query"
        assert q != 42

    def test_query_is_hashable(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetOrdersByCustomer(customer_id="C-123")
        assert hash(q) is not None

    def test_equal_queries_have_same_hash(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q1 = GetOrdersByCustomer(customer_id="C-123", status="pending")
        q2 = GetOrdersByCustomer(customer_id="C-123", status="pending")
        assert hash(q1) == hash(q2)

    def test_query_can_be_used_in_set(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q1 = GetOrdersByCustomer(customer_id="C-123")
        q2 = GetOrdersByCustomer(customer_id="C-123")
        q3 = GetOrdersByCustomer(customer_id="C-456")

        s = {q1, q2, q3}
        assert len(s) == 2


class TestQueryTemplateDictPattern:
    def test_query_from_template_dict(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetOrdersByCustomer(
            {"customer_id": "C-123", "status": "pending"},
            page=2,
        )
        assert q.customer_id == "C-123"
        assert q.status == "pending"
        assert q.page == 2

    def test_kwargs_override_template_dict(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetOrdersByCustomer(
            {"customer_id": "C-123", "status": "pending"},
            status="shipped",
        )
        assert q.status == "shipped"

    def test_non_dict_positional_arg_raises(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        with pytest.raises(AssertionError, match="must be a dict"):
            GetOrdersByCustomer("not a dict")


class TestQueryHasNoMessageInfrastructure:
    """Confirm that queries have no message/event store infrastructure."""

    def test_query_has_no_metadata(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetOrdersByCustomer(customer_id="C-123")
        assert not hasattr(q, "_metadata")

    def test_query_has_no_type_string(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        assert not hasattr(GetOrdersByCustomer, "__type__")

    def test_query_not_in_events_and_commands(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        for type_string in test_domain._events_and_commands:
            assert "GetOrdersByCustomer" not in type_string

    def test_query_has_no_aggregate_cluster(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.init(traverse=False)

        assert not hasattr(GetOrdersByCustomer.meta_, "aggregate_cluster")
