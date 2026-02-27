"""Tests that Reference._fetch_objects uses the repository's public API,
not the DAO directly.

Fix #1 from audit: Reference field should go through repo.find_by()
to honor aggregate boundaries in DDD.
"""

import inspect

import pytest

from protean.fields.association import Reference

from .elements import Account, Author


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(Author, part_of=Account)
    test_domain.init(traverse=False)


class TestReferenceFetchUsesRepository:
    def test_fetch_objects_delegates_through_repository_not_dao(self):
        """Reference._fetch_objects must call repo.find_by() (the public
        repository API) rather than repo._dao.find_by() (bypassing the
        aggregate boundary).

        We verify this structurally: the method body should reference
        `.find_by(` but never `._dao.`.
        """
        source = inspect.getsource(Reference._fetch_objects)
        assert ".find_by(" in source, (
            "Reference._fetch_objects should call repo.find_by()"
        )
        assert "._dao." not in source, (
            "Reference._fetch_objects should not bypass the repository "
            "by accessing ._dao directly"
        )

    def test_lazy_load_returns_correct_aggregate(self, test_domain):
        """Lazy-loading a Reference field should return the correct
        aggregate with all attributes intact."""
        account = Account(
            email="jane.doe@gmail.com",
            password="x1y2z3",
            username="janedoe",
            author=Author(first_name="Jane", last_name="Doe"),
        )
        test_domain.repository_for(Account).add(account)

        author = test_domain.repository_for(Account).get(account.email).author
        assert "account" not in author.__dict__

        # Trigger lazy load
        loaded = author.account
        assert loaded.email == "jane.doe@gmail.com"
        assert loaded.password == "x1y2z3"
        assert loaded.username == "janedoe"

    def test_lazy_load_caches_result(self, test_domain):
        """After the first lazy load, subsequent accesses should use
        the cached value without re-fetching."""
        account = Account(
            email="john.doe@gmail.com",
            password="a1b2c3",
            author=Author(first_name="John", last_name="Doe"),
        )
        test_domain.repository_for(Account).add(account)

        author = test_domain.repository_for(Account).get(account.email).author
        assert "account" not in author.__dict__

        # First access triggers lazy load
        first_load = author.account
        assert "account" in author.__dict__

        # Second access uses cache
        second_load = author.account
        assert first_load.email == second_load.email
