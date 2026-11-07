"""Filter paths of the Elasticsearch DAO: OR criteria and the unmapped-sort retry."""

import logging

import pytest

from protean import Q
from protean.exceptions import DatabaseError

from .elements import Person


@pytest.mark.elasticsearch
class TestFilterPaths:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.init(traverse=False)

    @pytest.fixture
    def dao(self, test_domain):
        dao = test_domain.repository_for(Person)._dao
        dao.create(first_name="Athos", last_name="Musketeer", age=30)
        dao.create(first_name="Porthos", last_name="Musketeer", age=40)
        dao.create(first_name="Aramis", last_name="Musketeer", age=50)
        return dao

    def test_unmapped_sort_field_retries_without_the_sort(self, dao, caplog):
        with caplog.at_level(logging.WARNING):
            result = dao._filter(Q(age__gte=10), order_by=["nonexistent"])

        assert sorted(item.first_name for item in result.items) == [
            "Aramis",
            "Athos",
            "Porthos",
        ]
        assert "retrying without sort" in caplog.text

    def test_failed_retry_raises_database_error(self, dao):
        # From offset 1, a None limit asks for documents 1 to 10001, past
        # Elasticsearch's default result window of 10000, so the retry fails.
        with pytest.raises(DatabaseError, match="Result window is too large"):
            dao._filter(Q(age__gte=10), offset=1, limit=None, order_by=["nonexistent"])

    @pytest.mark.xfail(
        strict=True,
        reason="the filter builder starts from match_all, and match_all OR x "
        "matches every document",
    )
    def test_or_of_plain_criteria_matches_either_criterion(self, dao):
        result = dao._filter(Q(first_name="Athos") | Q(age=50))

        assert sorted(item.first_name for item in result.items) == [
            "Aramis",
            "Athos",
        ]

    @pytest.mark.xfail(
        strict=True,
        reason="the filter builder starts from match_all, and match_all OR x "
        "matches every document",
    )
    def test_or_with_a_nested_criterion_matches_either_side(self, dao):
        result = dao._filter(
            Q(first_name="Athos") | (Q(age=50) & Q(last_name="Musketeer"))
        )

        assert sorted(item.first_name for item in result.items) == [
            "Aramis",
            "Athos",
        ]
