"""The `DAO` service's public read path: `fetch`, `count` and `raw`."""

from unittest.mock import PropertyMock, patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.queryset import Record
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import NotSupportedError
from protean.fields import HasMany, Integer, String
from protean.port.database import DatabaseCapabilities
from protean.utils.globals import current_uow
from protean.utils.query import Q

from .elements import Person


class Shelf(BaseAggregate):
    name: String(max_length=50, required=True)
    books = HasMany("Book")


class Book(BaseEntity):
    title: String(max_length=50, required=True)
    pages: Integer(default=0)


def _tracked(person):
    return current_uow._tracked_instance(Person, person.id)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(Shelf)
    test_domain.register(Book, part_of=Shelf)
    test_domain.init(traverse=False)


@pytest.fixture
def dao(test_domain):
    dao = test_domain.repository_for(Person)._dao
    dao.create(first_name="John", last_name="Doe", age=22)
    dao.create(first_name="Jane", last_name="Doe", age=18)
    dao.create(first_name="Baby", last_name="Roe", age=2)
    return dao


class TestFetch:
    def test_fetch_returns_matching_entities_marked_retrieved(self, dao):
        results = dao.fetch(Q(last_name="Doe"))

        assert results.total == 2
        assert sorted(p.first_name for p in results.items) == ["Jane", "John"]
        assert all(isinstance(p, Person) for p in results.items)
        assert all(p.state_.is_persisted for p in results.items)
        assert not any(p.state_.is_new for p in results.items)

    def test_fetch_passes_offset_limit_and_order_by(self, dao):
        results = dao.fetch(Q(), offset=1, limit=1, order_by=["age"])

        assert [p.first_name for p in results.items] == ["Jane"]
        assert results.total == 3

    def test_fetch_with_fields_returns_records(self, dao):
        results = dao.fetch(Q(last_name="Roe"), fields=["first_name"])

        assert len(results.items) == 1
        record = results.items[0]
        assert isinstance(record, Record)
        assert record.first_name == "Baby"

    def test_fetch_with_fields_tracks_nothing_in_the_unit_of_work(self, dao):
        with UnitOfWork():
            results = dao.fetch(Q(), fields=["id", "first_name"])
            assert len(results.items) == 3
            assert all(isinstance(r, Record) for r in results.items)
            assert not any(current_uow._identity_map.values())

    def test_fetch_inside_a_unit_of_work_tracks_each_aggregate(self, dao):
        with UnitOfWork():
            results = dao.fetch(Q(last_name="Doe"))
            assert len(results.items) == 2
            for person in results.items:
                assert _tracked(person) is person

    def test_fetch_returns_the_instance_the_unit_of_work_tracks(self, test_domain, dao):
        john = dao.find_by(first_name="John")
        repo = test_domain.repository_for(Person)

        with UnitOfWork():
            loaded = repo.get(john.id)
            fetched = dao.fetch(Q(first_name="John")).items

            assert len(fetched) == 1
            assert fetched[0] is loaded

    def test_fetch_outside_uow_registers_nothing(self, test_domain, dao):
        with UnitOfWork():
            outside = test_domain.repository_for(Person)._dao.outside_uow()
            results = outside.fetch(Q())

            assert len(results.items) == 3
            assert not any(current_uow._identity_map.values())

    def test_fetch_of_a_non_aggregate_entity_returns_it_untracked(self, test_domain):
        shelf = Shelf(name="Fiction", books=[Book(title="Dune", pages=412)])
        test_domain.repository_for(Shelf).add(shelf)
        book_dao = test_domain.repository_for(Book)._dao

        with UnitOfWork():
            results = book_dao.fetch(Q(title="Dune"))

            assert len(results.items) == 1
            book = results.items[0]
            assert isinstance(book, Book)
            assert book.pages == 412
            assert book.state_.is_persisted
            assert not any(current_uow._identity_map.values())


class TestCount:
    def test_count_returns_the_number_of_matching_rows(self, dao):
        assert dao.count(Q(last_name="Doe")) == 2
        assert dao.count(Q(last_name="Nobody")) == 0

    def test_count_ignores_the_queryset_offset_and_limit(self, dao):
        assert dao.query.offset(1).limit(1).count() == 3


class TestRaw:
    @pytest.fixture(autouse=True)
    def require_raw_queries(self, test_domain):
        provider = test_domain.repository_for(Person)._dao.provider
        if provider.__class__.__name__ != "MemoryDatabase":
            pytest.skip("The raw query below is in the memory provider's syntax")

    def test_raw_returns_entities_marked_retrieved(self, dao):
        results = dao.raw('{"last_name": "Roe"}')

        assert [p.first_name for p in results.items] == ["Baby"]
        assert results.items[0].state_.is_persisted

    def test_raw_returns_the_instance_the_unit_of_work_tracks(self, test_domain, dao):
        john = dao.find_by(first_name="John")
        repo = test_domain.repository_for(Person)

        with UnitOfWork():
            loaded = repo.get(john.id)
            raw_items = dao.raw('{"first_name": "John"}').items

            assert len(raw_items) == 1
            assert raw_items[0] is loaded


class TestRawWithoutCapability:
    @pytest.fixture
    def without_raw_queries(self, dao):
        provider = dao.provider
        caps = provider.capabilities & ~DatabaseCapabilities.RAW_QUERIES
        with patch.object(
            type(provider),
            "capabilities",
            new_callable=PropertyMock,
            return_value=caps,
        ):
            yield provider

    def test_raw_raises_naming_the_provider(self, dao, without_raw_queries):
        provider = without_raw_queries
        with pytest.raises(NotSupportedError) as exc_info:
            dao.raw("SELECT 1")

        message = str(exc_info.value)
        assert f"Provider '{provider.name}'" in message
        assert provider.__class__.__name__ in message
        assert "does not support raw queries" in message

    def test_queryset_raw_raises_and_keeps_its_cache(self, dao, without_raw_queries):
        query = dao.query.filter(last_name="Doe")
        query.all()
        cached = query._result_cache
        assert cached is not None

        with pytest.raises(NotSupportedError, match="does not support raw queries"):
            query.raw("SELECT 1")

        assert query._result_cache is cached
