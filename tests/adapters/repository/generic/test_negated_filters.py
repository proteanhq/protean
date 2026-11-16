"""Generic tests for negated filter expressions on every database provider.

``~`` negates the whole expression it wraps, including one that combines
conditions with ``|`` or ``&``. ``exclude()`` with several keywords keeps its
meaning and drops a record that matches any of them.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import String
from protean.utils.query import Q


class Pet(BaseAggregate):
    kind: String(max_length=20)
    name: String(max_length=20)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Pet)


def _on_elasticsearch(request):
    return request.config.getoption("--db", "MEMORY").upper() == "ELASTICSEARCH"


@pytest.fixture
def skip_on_elasticsearch(request):
    # Elasticsearch matches a document with a missing field on a negated
    # condition, unlike SQL's three-valued NOT.
    if _on_elasticsearch(request):
        pytest.skip("Elasticsearch matches NULL on a negated condition")


@pytest.fixture
def only_on_elasticsearch(request):
    if not _on_elasticsearch(request):
        pytest.skip("Only Elasticsearch matches NULL on a negated condition")


def _create(test_domain, **values):
    return test_domain.repository_for(Pet)._dao.create(**values).id


def _ids(test_domain, *args, exclude=False, **kwargs):
    query = test_domain.repository_for(Pet)._dao.query.limit(None)
    results = (
        query.exclude(*args, **kwargs) if exclude else query.filter(*args, **kwargs)
    )
    return {pet.id for pet in results.all().items}


@pytest.fixture
def kinds(test_domain, db):
    return {
        "cat": _create(test_domain, kind="cat"),
        "dog": _create(test_domain, kind="dog"),
        "fish": _create(test_domain, kind="fish"),
        "none": _create(test_domain, name="Nameless"),
    }


@pytest.fixture
def pets(test_domain, db):
    return {
        "dog_rex": _create(test_domain, kind="dog", name="Rex"),
        "dog_max": _create(test_domain, kind="dog", name="Max"),
        "cat_rex": _create(test_domain, kind="cat", name="Rex"),
    }


@pytest.mark.basic_storage
class TestNegatedOr:
    def test_negated_or_matches_the_and_of_negations(self, test_domain, kinds):
        negated_or = _ids(test_domain, ~(Q(kind="dog") | Q(kind="fish")))
        and_of_negations = _ids(test_domain, ~Q(kind="dog") & ~Q(kind="fish"))

        assert kinds["cat"] in negated_or
        assert negated_or == and_of_negations

    def test_negated_or_leaves_out_null(
        self, test_domain, kinds, skip_on_elasticsearch
    ):
        assert _ids(test_domain, ~(Q(kind="dog") | Q(kind="fish"))) == {kinds["cat"]}

    def test_negated_or_matches_a_missing_field_on_elasticsearch(
        self, test_domain, kinds, only_on_elasticsearch
    ):
        assert _ids(test_domain, ~(Q(kind="dog") | Q(kind="fish"))) == {
            kinds["cat"],
            kinds["none"],
        }


@pytest.mark.basic_storage
class TestNegatedAnd:
    def test_negated_and_excludes_only_records_matching_both(self, test_domain, pets):
        assert _ids(test_domain, ~(Q(kind="dog") & Q(name="Rex"))) == {
            pets["dog_max"],
            pets["cat_rex"],
        }

    def test_negated_multi_keyword_q_means_not_both(self, test_domain, pets):
        assert _ids(test_domain, ~Q(kind="dog", name="Rex")) == {
            pets["dog_max"],
            pets["cat_rex"],
        }

    def test_exclude_with_two_keywords_drops_a_record_matching_either(
        self, test_domain, pets
    ):
        assert _ids(test_domain, exclude=True, kind="dog", name="Rex") == set()

    def test_exclude_with_one_keyword(self, test_domain, pets):
        assert _ids(test_domain, exclude=True, kind="dog") == {pets["cat_rex"]}

    def test_negated_and_with_null(self, test_domain, pets, skip_on_elasticsearch):
        nameless_cat = _create(test_domain, kind="cat")

        # NOT dog holds, so NOT (dog AND Rex) holds.
        assert nameless_cat in _ids(test_domain, ~(Q(kind="dog") & Q(name="Rex")))
        # NOT cat is false and NOT (name = 'Rex') is unknown on NULL.
        assert _ids(test_domain, ~(Q(kind="cat") & Q(name="Rex"))) == {
            pets["dog_rex"],
            pets["dog_max"],
        }


@pytest.mark.basic_storage
class TestNestedNegation:
    def test_double_negation(self, test_domain, pets):
        assert _ids(test_domain, ~~Q(kind="dog")) == {
            pets["dog_rex"],
            pets["dog_max"],
        }

    def test_triple_negation_of_an_or(self, test_domain, pets):
        assert _ids(test_domain, ~~~(Q(kind="cat") | Q(name="Max"))) == {
            pets["dog_rex"]
        }

    def test_negated_or_containing_an_and(self, test_domain, pets):
        expression = ~(Q(kind="dog") | (Q(kind="cat") & Q(name="Rex")))
        assert _ids(test_domain, expression) == set()

    def test_negated_or_containing_a_partial_and(self, test_domain, pets):
        expression = ~(Q(name="Max") | (Q(kind="cat") & Q(name="Rex")))
        assert _ids(test_domain, expression) == {pets["dog_rex"]}

    def test_negated_and_under_an_or(self, test_domain, pets):
        expression = Q(kind="cat") | ~(Q(kind="dog") & Q(name="Rex"))
        assert _ids(test_domain, expression) == {pets["dog_max"], pets["cat_rex"]}

    def test_negated_or_containing_a_negated_or(self, test_domain, pets):
        # NOT (NOT (dog OR Max) OR Rex) == (dog OR Max) AND NOT Rex
        expression = ~(~(Q(kind="dog") | Q(name="Max")) | Q(name="Rex"))
        assert _ids(test_domain, expression) == {pets["dog_max"]}

    def test_exclude_with_a_negated_or(self, test_domain, pets):
        # exclude(NOT (cat OR Max)) keeps the records matching cat OR Max.
        assert _ids(test_domain, ~(Q(kind="cat") | Q(name="Max")), exclude=True) == {
            pets["cat_rex"],
            pets["dog_max"],
        }


@pytest.mark.basic_storage
class TestExcludeWithAPositionalQ:
    def test_exclude_with_an_or(self, test_domain, pets):
        assert _ids(test_domain, Q(kind="cat") | Q(name="Max"), exclude=True) == {
            pets["dog_rex"]
        }

    def test_exclude_with_a_single_condition_q(self, test_domain, pets):
        assert _ids(test_domain, Q(kind="dog"), exclude=True) == {pets["cat_rex"]}

    def test_exclude_with_a_multi_keyword_q_drops_records_matching_both(
        self, test_domain, pets
    ):
        assert _ids(test_domain, Q(kind="dog", name="Rex"), exclude=True) == {
            pets["dog_max"],
            pets["cat_rex"],
        }

    def test_exclude_negates_each_positional_q_on_its_own(self, test_domain, pets):
        assert _ids(test_domain, Q(kind="dog"), Q(name="Rex"), exclude=True) == set()

    def test_exclude_with_a_q_and_a_keyword(self, test_domain, pets):
        # NOT (cat OR fish) AND NOT Rex
        expression = Q(kind="cat") | Q(kind="fish")
        assert _ids(test_domain, expression, exclude=True, name="Rex") == {
            pets["dog_max"]
        }


@pytest.mark.basic_storage
class TestEmptyQ:
    def test_negated_empty_q_filters_nothing(self, test_domain, pets):
        assert _ids(test_domain, ~Q()) == set(pets.values())

    def test_negated_empty_q_keeps_the_condition_it_is_combined_with(
        self, test_domain, pets
    ):
        assert _ids(test_domain, ~Q() & Q(kind="dog")) == {
            pets["dog_rex"],
            pets["dog_max"],
        }

    def test_exclude_with_an_empty_q_drops_nothing(self, test_domain, pets):
        assert _ids(test_domain, Q(), exclude=True) == set(pets.values())

    def test_exclude_with_an_empty_q_and_a_keyword(self, test_domain, pets):
        assert _ids(test_domain, Q(), exclude=True, kind="dog") == {pets["cat_rex"]}
