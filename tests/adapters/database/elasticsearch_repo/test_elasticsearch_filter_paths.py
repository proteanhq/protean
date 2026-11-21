"""Filter paths of the Elasticsearch DAO: the unmapped-sort retry, and OR criteria
in filters, counts, updates and deletes."""

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
            result = dao.fetch(Q(age__gte=10), order_by=["nonexistent"])

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
            dao.fetch(Q(age__gte=10), offset=1, limit=None, order_by=["nonexistent"])

    def test_or_of_plain_criteria_matches_either_criterion(self, dao):
        result = dao.fetch(Q(first_name="Athos") | Q(age=50))

        assert sorted(item.first_name for item in result.items) == [
            "Aramis",
            "Athos",
        ]

    def test_or_with_a_nested_criterion_matches_either_side(self, dao):
        result = dao.fetch(
            Q(first_name="Athos") | (Q(age=50) & Q(last_name="Musketeer"))
        )

        assert sorted(item.first_name for item in result.items) == [
            "Aramis",
            "Athos",
        ]

    def test_or_with_an_unmatched_side_matches_only_the_other_side(self, dao):
        result = dao.fetch(Q(first_name="Athos") | Q(age=99))

        assert [item.first_name for item in result.items] == ["Athos"]

    def test_three_way_or_with_an_unmatched_part_matches_the_other_parts(self, dao):
        result = dao.fetch(Q(first_name="Athos") | (Q(age=40) | Q(age=99)))

        assert sorted(item.first_name for item in result.items) == [
            "Athos",
            "Porthos",
        ]

    def test_or_where_no_side_matches_matches_nothing(self, dao):
        result = dao.fetch(Q(first_name="Nobody") | Q(age=99))

        assert result.items == []

    def test_and_of_two_ors_matches_only_documents_in_both(self, dao):
        result = dao.fetch((Q(age=30) | Q(age=40)) & (Q(age=40) | Q(age=50)))

        assert [item.first_name for item in result.items] == ["Porthos"]

    def test_count_with_an_or_counts_only_matching_documents(self, dao):
        assert dao.count(Q(first_name="Athos") | Q(age=50)) == 2

    def test_update_all_with_an_or_updates_only_matching_documents(self, dao):
        updated = dao.update_all(
            Q(first_name="Athos") | Q(age=50), {"last_name": "Updated"}
        )

        assert updated == 2
        result = dao.fetch(Q(last_name="Updated"))
        assert sorted(item.first_name for item in result.items) == [
            "Aramis",
            "Athos",
        ]

    def test_update_all_guarded_on_the_version_writes_the_next_version(
        self, test_domain, dao
    ):
        [athos] = dao.fetch(Q(first_name="Athos")).items
        version = athos._version

        updated = dao.update_all(
            Q(id=athos.id, _version=version), {"age": 31, "_version": version + 1}
        )

        assert updated == 1
        stored = test_domain.repository_for(Person).get(athos.id)
        assert stored.age == 31
        assert stored._version == version + 1

    def test_update_all_guarded_on_a_stale_version_matches_nothing(
        self, test_domain, dao
    ):
        [athos] = dao.fetch(Q(first_name="Athos")).items
        version = athos._version

        updated = dao.update_all(
            Q(id=athos.id, _version=version + 1), {"age": 31, "_version": version + 2}
        )

        assert updated == 0
        stored = test_domain.repository_for(Person).get(athos.id)
        assert stored.age == 30
        assert stored._version == version

    def test_delete_all_with_an_or_deletes_only_matching_documents(self, dao):
        deleted = dao.delete_all(Q(first_name="Athos") | Q(age=50))

        assert deleted == 2
        remaining = dao.fetch(Q())
        assert [item.first_name for item in remaining.items] == ["Porthos"]

    def test_delete_top_with_an_or_deletes_only_matching_documents(self, dao):
        deleted = dao.delete_top(Q(first_name="Athos") | Q(age=50), limit=10)

        assert deleted == 2
        remaining = dao.fetch(Q())
        assert [item.first_name for item in remaining.items] == ["Porthos"]
