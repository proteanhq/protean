"""The write path puts a persisted aggregate's version back when its save
fails, and the `DAO` exposes the pre-persist hooks and the flush as public
methods."""

import pytest

from protean.core.unit_of_work import UnitOfWork

from .elements import Person


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.init(traverse=False)


@pytest.fixture
def dao(test_domain):
    return test_domain.repository_for(Person)._dao


def _fail(*args, **kwargs):
    raise RuntimeError("store down")


class TestAFailedSaveRestoresTheVersion:
    def test_a_failed_update_puts_the_version_back(self, dao, monkeypatch):
        person = dao.save(Person(first_name="John", last_name="Doe"))
        assert person._version == 0
        next_version = person._next_version

        monkeypatch.setattr(dao._adapter, "update", _fail)
        person.last_name = "Dane"
        with pytest.raises(RuntimeError, match="store down"):
            dao.save(person)

        assert person._version == 0
        assert person._next_version == next_version

    def test_a_failed_first_save_leaves_the_version_advanced(self, dao, monkeypatch):
        person = Person(first_name="John", last_name="Doe")
        assert person._version == -1

        monkeypatch.setattr(dao._adapter, "insert", _fail)
        with pytest.raises(RuntimeError, match="store down"):
            dao.save(person)

        assert person._version == 0
        assert not person.state_.is_persisted

    def test_a_raising_enricher_puts_the_version_back(self, test_domain, dao):
        person = dao.save(Person(first_name="John", last_name="Doe"))
        assert person._version == 0

        test_domain.register_aggregate_enricher(_fail)
        person.last_name = "Dane"
        with pytest.raises(RuntimeError, match="store down"):
            dao.save(person)

        assert person._version == 0
        assert dao.get(person.id).last_name == "Doe"


class TestPublicWriteMethods:
    def test_apply_pre_persist_hooks_runs_the_enrichers(self, test_domain, dao):
        def tag(person):
            person.last_name = "Enriched"

        test_domain.register_aggregate_enricher(tag)
        person = Person(first_name="John", last_name="Doe")

        dao.apply_pre_persist_hooks(person)

        assert person.last_name == "Enriched"
        assert not person.state_.is_persisted

    def test_flush_runs_inside_a_unit_of_work(self, dao):
        person = Person(first_name="John", last_name="Doe")
        with UnitOfWork():
            dao.save(person)
            dao.flush()

        assert dao.get(person.id).first_name == "John"
