"""The queries on the Retrieve Aggregates guide return what the page says.

The page seeds six people and runs its queries against them. The examples in
``docs_src/guides/change-state/retrieve-aggregates/`` run the same queries when
they load, so these tests check the results the examples kept. The REPL
sessions on the page are not run by the page runner, so these tests repeat
them against the same six people and check the output the page shows.
"""

import pytest

from protean import Index
from protean._deprecation import RemovedInProtean10Warning
from protean.exceptions import (
    NotSupportedError,
    ObjectNotFoundError,
    TooManyObjectsError,
)
from protean.utils.query import Q
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

SIX_PEOPLE = [
    ("John Doe", 38, "CA"),
    ("John Roe", 41, "US"),
    ("Jane Doe", 36, "CA"),
    ("Baby Doe", 3, "CA"),
    ("Boy Doe", 8, "CA"),
    ("Girl Doe", 11, "CA"),
]


def names(people):
    return [person.name for person in people]


@pytest.fixture
def queries():
    # Loading the example runs every query on the page, including the
    # deprecated bulk `update`.
    with pytest.warns(RemovedInProtean10Warning):
        module = load_example("guides/change-state/retrieve-aggregates/001.py")
    return module


@pytest.fixture
def indexed():
    module = load_example("guides/change-state/retrieve-aggregates/005.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


@pytest.fixture
def people():
    """The Person aggregate the page shows, with the six people added."""
    module = load_example("guides/change-state/005.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        repository = module.domain.repository_for(module.Person)
        for name, age, country in SIX_PEOPLE:
            repository.add(module.Person(name=name, age=age, country=country))
        yield repository


class TestGetByIdentity:
    def test_get_returns_the_person_with_the_identity(self):
        module = load_example("guides/change-state/001.py")
        with module.domain.domain_context():
            person = module.domain.repository_for(module.Person).get("1")
            assert person.name == "John Doe"
            assert person.email == "john.doe@localhost"

    def test_get_raises_when_no_person_has_the_identity(self):
        module = load_example("guides/change-state/001.py")
        with module.domain.domain_context():
            repository = module.domain.repository_for(module.Person)
            assert repository.get("1").name == "John Doe"
            with pytest.raises(ObjectNotFoundError):
                repository.get("2")


class TestTheShownQueries:
    def test_and_finds_the_adults_named_doe(self, queries):
        assert sorted(names(queries.adults_named_doe)) == ["Jane Doe", "John Doe"]

    def test_or_finds_people_under_5_or_over_40(self, queries):
        assert sorted(names(queries.under_5_or_over_40)) == ["Baby Doe", "John Roe"]

    def test_not_finds_everyone_outside_the_us(self, queries):
        assert sorted(names(queries.outside_us)) == [
            "Baby Doe",
            "Boy Doe",
            "Girl Doe",
            "Jane Doe",
            "John Doe",
        ]

    def test_nesting_finds_adults_in_ca_or_children_in_us(self, queries):
        # There are no children in the US, so only the adults in CA match.
        assert sorted(names(queries.ca_adults_or_us_children)) == [
            "Jane Doe",
            "John Doe",
        ]

    def test_q_and_keywords_together_find_john_doe_and_the_baby_in_ca(self, queries):
        assert sorted(names(queries.ca_john_doe_or_under_5)) == [
            "Baby Doe",
            "John Doe",
        ]

    def test_order_by_two_fields_sorts_by_country_then_age_descending(self, queries):
        assert names(queries.by_country_then_age) == [
            "John Doe",
            "Jane Doe",
            "Girl Doe",
            "Boy Doe",
            "Baby Doe",
            "John Roe",
        ]

    def test_limit_caps_the_page_and_none_removes_the_cap(self, queries):
        assert queries.limited_query.limit == 10
        assert queries.limited_query.total == 6
        assert queries.unlimited_query.limit is None
        assert len(queries.unlimited_query.items) == 6

    def test_pagination_properties_describe_the_second_page(self, queries):
        assert queries.page == 2
        assert queries.page_size == 10
        assert queries.total_pages == 1
        assert queries.has_next is False
        # Offset 10 is past the six people, so the page is empty and
        # has_prev is False even though this is not the first page.
        assert queries.result.items == []
        assert queries.has_prev is False

    def test_all_without_total_counts_only_the_rows_on_the_page(self, queries):
        assert names(queries.items) == ["Baby Doe", "Boy Doe"]
        # Five people live in CA. Without the count query, the memory adapter
        # sets the total to the two rows it returned.
        assert queries.youngest.total == 2

    def test_only_returns_records_with_the_projected_fields(self, queries):
        records = queries.records
        assert len(records) == 5
        assert sorted((record.name, record.age) for record in records) == [
            ("Baby Doe", 3),
            ("Boy Doe", 8),
            ("Girl Doe", 11),
            ("Jane Doe", 36),
            ("John Doe", 38),
        ]
        assert all(record.id for record in records)
        with pytest.raises(AttributeError):
            records[0].country

    def test_update_and_delete_remove_the_children_in_ca(self, queries):
        assert queries.updated_count == 3
        assert queries.deleted_count == 3
        with queries.domain.domain_context():
            remaining = queries.repository.query.all().items
        assert sorted(names(remaining)) == ["Jane Doe", "John Doe", "John Roe"]

    def test_raw_query_finds_john_doe_and_not_the_minor_with_his_name(self, queries):
        assert [(p.name, p.age) for p in queries.results.items] == [("John Doe", 38)]


class TestTheShownRepositoryMethods:
    def test_adults_in_country_returns_the_adults_in_ca(self, queries):
        with queries.domain.domain_context():
            adults = queries.repository.adults_in_country("CA")
        assert sorted(names(adults)) == ["Jane Doe", "John Doe"]

    def test_children_by_age_orders_the_children_youngest_first(self, queries):
        with queries.domain.domain_context():
            repository = queries.repository
            # The example's bulk delete removed the children, so add them back.
            for name, age, country in SIX_PEOPLE[3:]:
                repository.add(queries.Person(name=name, age=age, country=country))
            assert names(repository.children_by_age("CA")) == [
                "Baby Doe",
                "Boy Doe",
                "Girl Doe",
            ]
            assert repository.children_by_age("US") == []

    def test_has_adults_in_country(self, queries):
        with queries.domain.domain_context():
            assert queries.has_adults_in_country(queries.repository, "US") is True
            assert queries.has_adults_in_country(queries.repository, "UK") is False

    def test_get_page_returns_the_requested_page(self, queries):
        with queries.domain.domain_context():
            first = queries.get_page(queries.repository, 1, page_size=2)
            second = queries.get_page(queries.repository, 2, page_size=2)
        assert len(first.items) == 2
        assert first.has_next is True
        assert first.has_prev is False
        assert second.page == 2
        assert len(second.items) == 1
        assert second.has_next is False
        assert second.has_prev is True
        assert sorted(names(first.items + second.items)) == [
            "Jane Doe",
            "John Doe",
            "John Roe",
        ]

    def test_a_page_past_the_end_is_empty_and_has_no_previous_page(self, queries):
        with queries.domain.domain_context():
            past_the_end = queries.get_page(queries.repository, 3, page_size=2)
            via_query = queries.repository.query.offset(10).limit(2).all()

        assert past_the_end.items == []
        assert past_the_end.has_prev is False
        assert past_the_end.has_next is False
        assert via_query.items == []
        assert via_query.has_prev is False


class TestTheShownSessions:
    """The REPL sessions on the page, run against the six people."""

    def test_find_by_returns_the_single_match(self, people):
        assert people.find_by(age=36, country="CA").name == "Jane Doe"

    def test_find_by_raises_for_no_match_and_for_many_matches(self, people):
        assert people.find_by(name="John Roe").age == 41
        with pytest.raises(ObjectNotFoundError):
            people.find_by(name="Nobody")
        with pytest.raises(TooManyObjectsError):
            people.find_by(country="CA")

    def test_find_returns_everyone_in_ca(self, people):
        results = people.find(Q(country="CA"))
        assert results.total == 5
        assert names(results.items) == [
            "John Doe",
            "Jane Doe",
            "Baby Doe",
            "Boy Doe",
            "Girl Doe",
        ]

    def test_find_with_composed_criteria_returns_the_adults_in_ca(self, people):
        results = people.find(Q(country="CA") & Q(age__gte=18))
        assert names(results.items) == ["John Doe", "Jane Doe"]

    def test_exists(self, people):
        assert people.exists(Q(country="US")) is True
        assert people.exists(Q(country="UK")) is False

    def test_filter_and_exclude(self, people):
        adults = people.query.filter(age__gte=18, country="CA").all().items
        assert names(adults) == ["John Doe", "Jane Doe"]
        not_us = people.query.exclude(country="US").all().items
        assert names(not_us) == [
            "John Doe",
            "Jane Doe",
            "Baby Doe",
            "Boy Doe",
            "Girl Doe",
        ]

    def test_chained_filters_and_order_by_name(self, people):
        adults_in_ca = (
            people.query.filter(age__gte=18)
            .filter(country="CA")
            .order_by("name")
            .all()
            .items
        )
        assert [f"{p.name}, {p.age}" for p in adults_in_ca] == [
            "Jane Doe, 36",
            "John Doe, 38",
        ]

    def test_lookups(self, people):
        assert people.query.filter(name__contains="Doe").all().total == 5
        assert people.query.filter(age__gt=10, age__lt=40).all().total == 3
        in_list = people.query.filter(name__in=["John Doe", "Jane Doe"]).all()
        assert in_list.total == 2

    def test_order_by_age_descending(self, people):
        ordered = people.query.order_by("-age").all().items
        assert [(p.name, p.age) for p in ordered] == [
            ("John Roe", 41),
            ("John Doe", 38),
            ("Jane Doe", 36),
            ("Girl Doe", 11),
            ("Boy Doe", 8),
            ("Baby Doe", 3),
        ]

    def test_queryset_properties_and_count(self, people):
        query = people.query.filter(country="CA").order_by("age")
        assert query.total == 5
        assert query.first.name == "Baby Doe"
        assert query.last.name == "John Doe"
        assert people.query.filter(country="CA").count() == 5

    def test_records_are_read_only_and_hold_only_the_projected_fields(self, people):
        record = people.query.only("name").all().first
        assert record.name == "John Doe"
        assert record["name"] == "John Doe"
        assert record.id
        with pytest.raises(AttributeError, match="age"):
            record.age
        with pytest.raises(NotSupportedError):
            record.name = "X"

    def test_only_cannot_update_or_delete_but_can_count(self, people):
        projected = people.query.filter(country="CA").only("name")
        assert projected.count() == 5
        with pytest.raises(NotSupportedError):
            projected.delete()
        with pytest.raises(NotSupportedError):
            projected.update(country="XX")
        assert people.query.filter(country="CA").count() == 5

    def test_result_set_to_dict(self, people):
        result = people.query.all()
        assert len(result) == 6
        as_dict = result.to_dict()
        assert {key: value for key, value in as_dict.items() if key != "items"} == {
            "offset": 0,
            "limit": 100,
            "total": 6,
            "page": 1,
            "page_size": 100,
            "total_pages": 1,
            "has_next": False,
            "has_prev": False,
        }
        assert sorted(names(as_dict["items"])) == sorted(
            name for name, _, _ in SIX_PEOPLE
        )


class TestNullAndFieldLookups:
    def test_isnull_separates_archived_from_never_archived(self):
        module = load_example("guides/change-state/retrieve-aggregates/002.py")
        assert [a.title for a in module.never_archived] == ["Draft"]
        assert [a.title for a in module.archived] == ["Old news"]

    def test_f_compares_two_fields_of_the_same_aggregate(self):
        module = load_example("guides/change-state/retrieve-aggregates/002.py")
        # (4, 5) is in and (2, 1) is out, so each row is compared with its own
        # `max_retries`, not with the default of 3.
        assert sorted((n.retry_count, n.max_retries) for n in module.retrying) == [
            (1, 3),
            (4, 5),
        ]


@pytest.fixture
def orders():
    return load_example("guides/change-state/retrieve-aggregates/003.py")


def ids(results):
    return sorted(order.id for order in results)


class TestComposableQueryFunctions:
    def test_composed_functions_find_the_matching_orders(self, orders):
        assert ids(orders.overdue.items) == ["A", "B", "E"]
        # E is overdue by two days, inside the three-day grace period.
        assert ids(orders.overdue_and_high_value.items) == ["A"]
        assert ids(orders.regional.items) == ["A", "C"]
        assert ids(orders.stale.items) == ["A", "C", "E"]
        assert orders.needs_escalation is True

    def test_functions_work_with_the_queryset(self, orders):
        assert ids(orders.overdue_in_us.items) == ["A"]

    def test_repository_methods_use_the_functions(self, orders):
        with orders.domain.domain_context():
            assert ids(orders.repo.critical_orders()) == ["A"]
            assert orders.repo.has_overdue_in_region("US") is True
            assert orders.repo.has_overdue_in_region("APAC") is False


class TestSpecifications:
    def test_to_query_finds_the_critical_orders(self, orders):
        assert ids(orders.results.items) == ["A"]

    def test_is_satisfied_by_matches_the_same_orders_in_memory(self, orders):
        with orders.domain.domain_context():
            by_id = {order.id: order for order in orders.repo.query.all().items}
        assert sorted(by_id) == ["A", "B", "C", "D", "E"]
        critical = orders.OverdueOrders(grace_days=3) & orders.HighValueOrders(
            min_amount=5000
        )
        assert [i for i in sorted(by_id) if critical.is_satisfied_by(by_id[i])] == ["A"]
        either = orders.OverdueOrders() | orders.HighValueOrders(min_amount=5000)
        assert [i for i in sorted(by_id) if either.is_satisfied_by(by_id[i])] == [
            "A",
            "B",
            "C",
            "E",
        ]
        not_overdue = ~orders.OverdueOrders()
        assert [i for i in sorted(by_id) if not_overdue.is_satisfied_by(by_id[i])] == [
            "C",
            "D",
        ]

    def test_remind_if_overdue_reminds_only_for_overdue_orders(self, orders):
        with orders.domain.domain_context():
            repo = orders.repo
            orders.remind_if_overdue(repo.get("B"))
            orders.remind_if_overdue(repo.get("D"))
        assert orders.reminders == ["B"]


class TestDefaultLimit:
    def test_queries_return_at_most_50_records_by_default(self):
        module = load_example("guides/change-state/retrieve-aggregates/004.py")
        module.domain.init(traverse=False)
        with module.domain.domain_context():
            repository = module.domain.repository_for(module.Person)
            for number in range(1, 61):
                repository.add(module.Person(id=number, name=f"Person {number}"))

            result = repository.query.all()
            assert result.limit == 50
            assert len(result.items) == 50
            assert result.total == 60
            assert len(repository.query.limit(None).all().items) == 60


class TestIndexes:
    def test_the_customer_declares_a_country_and_age_descending_index(self, indexed):
        assert indexed.Customer.meta_.indexes == [
            Index("country", "age", desc=("age",))
        ]

    def test_the_indexed_query_finds_us_customers_oldest_first(self, indexed):
        repo = indexed.domain.repository_for(indexed.Customer)
        for country, age in [("US", 30), ("CA", 50), ("US", 45)]:
            repo.add(indexed.Customer(country=country, age=age))

        customers = repo.query.filter(country="US").order_by("-age").all()

        assert [customer.age for customer in customers.items] == [45, 30]
