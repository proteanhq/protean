"""Generic QuerySet tests that run against all database providers.

Covers QuerySet limit behavior and pagination, ``count()`` totals, and
``only()`` field projection into read-only Records.
"""

import pytest

from protean import Record
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import Float, HasMany, Integer, String


class OrderItem(BaseEntity):
    product_id: String(max_length=50)
    quantity: Integer()
    price: Float()


class Order(BaseAggregate):
    items = HasMany(OrderItem)


@pytest.mark.basic_storage
class TestQuerySetLimit:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)

    def test_default_queryset_limit_is_applied(self, test_domain):
        # Create an order with 101 items
        order = Order(
            items=[
                OrderItem(product_id=f"PROD-{i}", quantity=1, price=9.99)
                for i in range(101)
            ]
        )
        test_domain.repository_for(Order).add(order)

        assert test_domain.repository_for(OrderItem).query._limit == 100

        # Fetch the order
        order = test_domain.repository_for(Order).get(order.id)

        # Verify that the order items are limited to 100 by default
        assert len(order.items) == 100

        # Verify that the order items are not limited when limit is set to None
        assert len(test_domain.repository_for(OrderItem).query.limit(None).all()) == 101

    def test_no_queryset_limit_is_applied_if_limit_is_set_to_none(self, test_domain):
        test_domain.register(OrderItem, part_of=Order, limit=None)

        # Create an order with 101 items
        order = Order(
            items=[
                OrderItem(product_id=f"PROD-{i}", quantity=1, price=9.99)
                for i in range(101)
            ]
        )
        test_domain.repository_for(Order).add(order)

        assert test_domain.repository_for(OrderItem).query._limit is None

        # Fetch the order
        order = test_domain.repository_for(Order).get(order.id)

        # Verify that the order items are not limited when limit is set to None
        assert len(order.items) == 101

    def test_queryset_limit_is_applied_if_limit_is_set(self, test_domain):
        test_domain.register(OrderItem, part_of=Order, limit=10)

        # Create an order with 101 items
        order = Order(
            items=[
                OrderItem(product_id=f"PROD-{i}", quantity=1, price=9.99)
                for i in range(101)
            ]
        )
        test_domain.repository_for(Order).add(order)

        assert test_domain.repository_for(OrderItem).query._limit == 10

        # Fetch the order
        order = test_domain.repository_for(Order).get(order.id)

        # Verify that the order items are limited to 10
        assert len(order.items) == 10

    def test_no_queryset_limit_is_applied_if_limit_is_set_to_negative_value(
        self, test_domain
    ):
        test_domain.register(OrderItem, part_of=Order, limit=-1)

        # Create an order with 101 items
        order = Order(
            items=[
                OrderItem(product_id=f"PROD-{i}", quantity=1, price=9.99)
                for i in range(101)
            ]
        )
        test_domain.repository_for(Order).add(order)

        assert test_domain.repository_for(OrderItem).query._limit is None

        # Fetch the order
        order = test_domain.repository_for(Order).get(order.id)

        # Verify that the order items are not limited when limit is set to None
        assert len(order.items) == 101


class Member(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)
    nickname: String(max_length=50)  # nullable — not required, no default


@pytest.mark.basic_storage
class TestQuerySetCount:
    """``count()`` returns adapter-agnostic integer totals without
    materializing entities. Every provider (including Elasticsearch) implements
    ``_count``."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Member)
        test_domain.init(traverse=False)

    def _seed(self, test_domain):
        repo = test_domain.repository_for(Member)
        repo.add(Member(first_name="Alice", last_name="Wonder", age=30))
        repo.add(Member(first_name="Bob", last_name="Wonder", age=40))
        repo.add(Member(first_name="Carol", last_name="Other", age=25))

    def test_count_on_empty_repository_is_zero(self, test_domain):
        assert test_domain.repository_for(Member).query.count() == 0

    def test_count_returns_total(self, test_domain):
        self._seed(test_domain)
        assert test_domain.repository_for(Member).query.count() == 3

    def test_count_with_filter(self, test_domain):
        self._seed(test_domain)
        repo = test_domain.repository_for(Member)
        assert repo.query.filter(last_name="Wonder").count() == 2
        assert repo.query.filter(age__gte=30).count() == 2

    def test_count_with_combined_criteria(self, test_domain):
        self._seed(test_domain)
        repo = test_domain.repository_for(Member)
        assert repo.query.filter(last_name="Wonder", age__gte=35).count() == 1

    def test_all_with_total_false_returns_items_without_full_count(self, test_domain):
        """``all(with_total=False)`` returns the same items on every adapter; the
        SQL adapter skips its separate ``COUNT`` round-trip (total reflects the
        returned page rather than the full match count)."""
        self._seed(test_domain)
        repo = test_domain.repository_for(Member)

        full = repo.query.filter(last_name="Wonder").all()
        lite = repo.query.filter(last_name="Wonder").all(with_total=False)

        assert {m.first_name for m in lite.items} == {m.first_name for m in full.items}
        assert len(lite.items) == 2
        assert lite.total == len(lite.items)


class Article(BaseAggregate):
    title: String(max_length=50, required=True)
    status: String(max_length=20, default="draft")
    body: String(max_length=5000)
    views: Integer(default=0)


@pytest.mark.basic_storage
class TestOnlyProjection:
    """``only()`` projects a subset of persisted fields into read-only Records
    (identity always included). Supported on every provider, including
    Elasticsearch (``_source`` filtering)."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Article)
        test_domain.init(traverse=False)

    @pytest.fixture
    def seeded_repo(self, test_domain, db):
        """Seed two Articles and return their repository.

        Depends on ``db`` so table/index setup precedes the inserts on SQL
        adapters.
        """
        repo = test_domain.repository_for(Article)
        repo.add(Article(title="Alpha", status="published", body="a" * 200, views=10))
        repo.add(Article(title="Beta", status="draft", body="b" * 200, views=5))
        return repo

    def test_only_selects_requested_fields(self, seeded_repo):
        records = (
            seeded_repo.query.order_by("title").only("status", "views").all().items
        )

        assert len(records) == 2
        assert all(isinstance(record, Record) for record in records)
        assert records[0].status == "published"
        assert records[0].views == 10

    def test_identifier_included_without_request(self, seeded_repo):
        record = seeded_repo.query.only("status").all().first

        assert record.id is not None

    def test_non_selected_field_absent(self, seeded_repo):
        record = seeded_repo.query.only("status").all().first

        assert "body" not in record
        with pytest.raises(AttributeError):
            _ = record.body

    def test_filter_combines_with_only(self, seeded_repo):
        records = seeded_repo.query.filter(status="published").only("title").all().items

        assert len(records) == 1
        assert records[0].title == "Alpha"
