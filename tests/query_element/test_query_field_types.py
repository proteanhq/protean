"""Tests for Query field type support.

Validates:
- Various field types work in queries (String, Integer, Float, Identifier, Boolean)
- List fields
- Optional and required ValueObject fields
- ValueObject serialization in to_dict()
"""

import pytest

from protean.core.query import BaseQuery
from protean.fields import (
    Boolean,
    Float,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
)

from .elements import Money, OrderSummary, ProductSearch


class TestBasicFieldTypes:
    def test_string_field(self, test_domain):
        class SearchByName(BaseQuery):
            name = String(max_length=100)

        test_domain.register(ProductSearch)
        test_domain.register(SearchByName, part_of=ProductSearch)
        test_domain.init(traverse=False)

        q = SearchByName(name="laptop")
        assert q.name == "laptop"

    def test_integer_field(self, test_domain):
        class GetPaged(BaseQuery):
            page = Integer(default=1)
            size = Integer(default=10)

        test_domain.register(OrderSummary)
        test_domain.register(GetPaged, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = GetPaged(page=3, size=50)
        assert q.page == 3
        assert q.size == 50

    def test_float_field(self, test_domain):
        class FilterByPrice(BaseQuery):
            min_price = Float(default=0.0)
            max_price = Float()

        test_domain.register(ProductSearch)
        test_domain.register(FilterByPrice, part_of=ProductSearch)
        test_domain.init(traverse=False)

        q = FilterByPrice(max_price=99.99)
        assert q.min_price == 0.0
        assert q.max_price == 99.99

    def test_identifier_field(self, test_domain):
        class GetById(BaseQuery):
            item_id = Identifier(required=True)

        test_domain.register(ProductSearch)
        test_domain.register(GetById, part_of=ProductSearch)
        test_domain.init(traverse=False)

        q = GetById(item_id="abc-123")
        assert q.item_id == "abc-123"

    def test_boolean_field(self, test_domain):
        class FilterActive(BaseQuery):
            active_only = Boolean(default=True)

        test_domain.register(OrderSummary)
        test_domain.register(FilterActive, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = FilterActive()
        assert q.active_only is True

        q2 = FilterActive(active_only=False)
        assert q2.active_only is False

    def test_list_field(self, test_domain):
        class FilterByStatuses(BaseQuery):
            statuses = List(content_type=String, default=list)

        test_domain.register(OrderSummary)
        test_domain.register(FilterByStatuses, part_of=OrderSummary)
        test_domain.init(traverse=False)

        q = FilterByStatuses(statuses=["pending", "shipped"])
        assert q.statuses == ["pending", "shipped"]


class TestValueObjectFields:
    def test_optional_value_object(self, test_domain):
        class SearchWithBudget(BaseQuery):
            keyword = String()
            budget = ValueObject(Money)

        test_domain.register(ProductSearch)
        test_domain.register(SearchWithBudget, part_of=ProductSearch)
        test_domain.init(traverse=False)

        q = SearchWithBudget(keyword="laptop")
        assert q.budget is None

        q2 = SearchWithBudget(
            keyword="laptop",
            budget=Money(amount=99.99, currency="USD"),
        )
        assert q2.budget.amount == 99.99
        assert q2.budget.currency == "USD"

    def test_required_value_object(self, test_domain):
        class SearchWithPrice(BaseQuery):
            min_price = ValueObject(Money, required=True)

        test_domain.register(ProductSearch)
        test_domain.register(SearchWithPrice, part_of=ProductSearch)
        test_domain.init(traverse=False)

        from protean.exceptions import ValidationError

        with pytest.raises(ValidationError):
            SearchWithPrice()

        q = SearchWithPrice(min_price=Money(amount=50.0, currency="EUR"))
        assert q.min_price.amount == 50.0

    def test_annotation_style_optional_vo(self, test_domain):
        """Cover annotation-style ValueObject descriptor: ``budget: ValueObject(Money)``."""

        class SearchAnnotated(BaseQuery):
            keyword: String(required=True)
            budget: ValueObject(Money)

        test_domain.register(ProductSearch)
        test_domain.register(SearchAnnotated, part_of=ProductSearch)
        test_domain.init(traverse=False)

        q = SearchAnnotated(keyword="tablet")
        assert q.budget is None

        q2 = SearchAnnotated(
            keyword="tablet",
            budget=Money(amount=200.0, currency="GBP"),
        )
        assert q2.budget.amount == 200.0
        assert q2.budget.currency == "GBP"

    def test_annotation_style_required_vo(self, test_domain):
        """Cover annotation-style required ValueObject descriptor."""

        class SearchAnnotatedRequired(BaseQuery):
            budget: ValueObject(Money, required=True)

        test_domain.register(ProductSearch)
        test_domain.register(SearchAnnotatedRequired, part_of=ProductSearch)
        test_domain.init(traverse=False)

        q = SearchAnnotatedRequired(budget=Money(amount=10.0))
        assert q.budget.amount == 10.0

    def test_vo_serialization_in_to_dict(self, test_domain):
        class SearchWithBudget(BaseQuery):
            keyword = String(required=True)
            budget = ValueObject(Money, required=True)

        test_domain.register(ProductSearch)
        test_domain.register(SearchWithBudget, part_of=ProductSearch)
        test_domain.init(traverse=False)

        q = SearchWithBudget(
            keyword="laptop",
            budget=Money(amount=50.0, currency="EUR"),
        )
        d = q.to_dict()
        assert d["keyword"] == "laptop"
        assert d["budget"] == {"amount": 50.0, "currency": "EUR"}
