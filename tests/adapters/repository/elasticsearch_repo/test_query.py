import pytest

from elasticsearch_dsl.query import Bool, Term

from .elements import Person


@pytest.mark.elasticsearch
class TestESQuery:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    def test_construction_of_single_attribute_filter(self, test_domain):
        q1 = test_domain.get_dao(Person).query.filter(first_name="Jane")
        assert q1._owner_dao._build_filters(q1._criteria) == Term(first_name="Jane")

    def test_construction_of_filter_with_two_attributes(self, test_domain):
        q1 = test_domain.get_dao(Person).query.filter(
            first_name="Jane", last_name="Doe"
        )
        q2 = (
            test_domain.get_dao(Person)
            .query.filter(first_name="Jane")
            .filter(last_name="Doe")
        )

        filters1 = q1._owner_dao._build_filters(q1._criteria)
        filters2 = q2._owner_dao._build_filters(q2._criteria)

        assert filters1 == Bool(must=[Term(first_name="Jane"), Term(last_name="Doe")])
        assert filters2 == Bool(must=[Term(first_name="Jane"), Term(last_name="Doe")])

    def test_construction_of_single_attribute_negation_filter(self, test_domain):
        q1 = test_domain.get_dao(Person).query.exclude(first_name="Jane")
        assert q1._owner_dao._build_filters(q1._criteria) == Bool(
            must_not=[Term(first_name="Jane")]
        )

    def test_construction_of_filter_with_two_negated_attributes(self, test_domain):
        q1 = test_domain.get_dao(Person).query.exclude(
            first_name="Jane", last_name="Doe"
        )
        q2 = (
            test_domain.get_dao(Person)
            .query.exclude(first_name="Jane")
            .exclude(last_name="Doe")
        )

        filters1 = q1._owner_dao._build_filters(q1._criteria)
        filters2 = q2._owner_dao._build_filters(q2._criteria)

        assert filters1 == Bool(
            must_not=[Term(first_name="Jane"), Term(last_name="Doe")]
        )
        assert filters2 == Bool(
            must_not=[Term(first_name="Jane"), Term(last_name="Doe")]
        )

    def test_construction_with_combined_filter_and_exclude_with_filter_coming_first(
        self, test_domain
    ):
        q1 = test_domain.get_dao(Person).query.filter(last_name="Doe").exclude(age=3)
        filters1 = q1._owner_dao._build_filters(q1._criteria)
        assert filters1 == Bool(must=[Term(last_name="Doe")], must_not=[Term(age=3)])

    def test_construction_with_combined_filter_and_exclude_with_exclude_coming_first(
        self, test_domain
    ):
        q1 = test_domain.get_dao(Person).query.exclude(age=3).filter(last_name="Doe")
        filters1 = q1._owner_dao._build_filters(q1._criteria)
        assert filters1 == Bool(must=[Term(last_name="Doe")], must_not=[Term(age=3)])
