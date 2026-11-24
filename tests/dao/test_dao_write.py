"""The write path puts a persisted aggregate's version back when its save
fails, checks unique fields on the deprecated ``update``, tracks a created
aggregate in the Unit of Work, and calls its patchable `DAO` methods. The
`DAO` exposes the pre-persist hooks and the flush as public methods."""

import warnings

import pytest

from protean._deprecation import RemovedInProtean020Warning
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ValidationError
from protean.infra.dao import DAO
from protean.port.database import DatabaseCapabilities
from protean.utils.globals import current_uow

from .elements import Person, User


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(User)
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

    def test_flush_flushes_the_unit_of_work_session(self, dao, monkeypatch):
        flushed = []
        monkeypatch.setattr(dao.provider, "flush", flushed.append)

        with UnitOfWork():
            dao.flush()
            uow_session = current_uow.get_session(dao.provider.name)

        assert flushed == [uow_session]


class TestDeprecatedUpdateChecksUniqueFields:
    def test_update_to_a_taken_unique_value_raises(self, test_domain):
        user_dao = test_domain.repository_for(User)._dao
        user_dao.create(email="john@example.com")
        jane = user_dao.create(email="jane@example.com")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RemovedInProtean020Warning)
            with pytest.raises(ValidationError) as exc:
                user_dao.update(jane, email="john@example.com")

        assert "email" in exc.value.messages
        assert user_dao.get(jane.id).email == "jane@example.com"


class TestCreateInAUnitOfWork:
    def test_create_tracks_the_aggregate_as_saved(self, dao):
        with UnitOfWork() as uow:
            person = dao.create(first_name="John", last_name="Doe")

            assert uow._tracked_instance(Person, person.id) is person
            assert (Person.meta_.database, Person, person.id) in uow._saved


class TestTheWritePathCallsTheDAOMethods:
    def test_save_runs_the_hooks_through_the_dao_method(self, dao, monkeypatch):
        seen = []
        monkeypatch.setattr(
            DAO, "apply_pre_persist_hooks", lambda self, entity: seen.append(entity)
        )
        person = Person(first_name="John", last_name="Doe")

        dao.save(person)

        assert seen == [person]

    def test_save_if_absent_falls_back_through_the_dao_method(self, dao, monkeypatch):
        monkeypatch.setattr(
            type(dao.provider),
            "capabilities",
            property(lambda self: DatabaseCapabilities.IN_MEMORY),
        )
        calls = []

        def key_free(self, entity, *, apply_hooks):
            calls.append((entity, apply_hooks))
            return "patched"

        monkeypatch.setattr(DAO, "_save_if_key_free", key_free)
        person = Person(first_name="John", last_name="Doe")

        assert dao.save_if_absent(person, apply_hooks=False) == "patched"
        assert calls == [(person, False)]
