import warnings

import pytest

from protean._deprecation import RemovedInProtean10Warning
from protean.exceptions import ObjectNotFoundError
from protean.utils.query import Q

from .elements import Person, PersonRepository, User


class TestDAOUpdateFunctionality:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, part_of=Person)
        test_domain.register(User)

    @pytest.fixture(autouse=True)
    def _ignore_update_deprecation(self):
        # These tests assert the persistence behaviour of the patch-and-persist
        # path, which is deprecated (see TestUpdateDeprecationWarning). Silence
        # the warning here so the behaviour assertions stay the focus.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RemovedInProtean10Warning)
            yield

    def test_update_an_existing_entity_in_the_repository(self, test_domain):
        person = test_domain.repository_for(Person)._dao.create(
            id=11344234, first_name="John", last_name="Doe", age=22
        )

        test_domain.repository_for(Person)._dao.update(person, age=10)
        updated_person = test_domain.repository_for(Person)._dao.get(11344234)
        assert updated_person is not None
        assert updated_person.age == 10

    def test_that_updating_a_deleted_aggregate_raises_object_not_found_error(
        self, test_domain
    ):
        """Try to update a non-existing entry"""

        person = test_domain.repository_for(Person)._dao.create(
            id=11344234, first_name="Johnny", last_name="John"
        )
        test_domain.repository_for(Person)._dao.delete(person)
        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.update(person, {"age": 10})

    def test_that_updating_an_unpersisted_entity_raises_object_not_found_error(
        self, test_domain
    ):
        """update() targets an existing record; a never-persisted entity must
        raise rather than silently create one (which delegating to save() would
        otherwise do via its create branch)."""
        fresh = Person(id=999, first_name="Never", last_name="Saved")
        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.update(fresh, age=10)

    def test_updating_record_with_dictionary_args(self, test_domain):
        """Update an existing entity in the repository"""
        person = test_domain.repository_for(Person)._dao.create(
            id=2, first_name="Johnny", last_name="John", age=2
        )

        test_domain.repository_for(Person)._dao.update(person, {"age": 10})
        u_person = test_domain.repository_for(Person)._dao.get(2)
        assert u_person is not None
        assert u_person.age == 10

    def test_updating_record_with_kwargs(self, test_domain):
        """Update an existing entity in the repository"""
        person = test_domain.repository_for(Person)._dao.create(
            id=2, first_name="Johnny", last_name="John", age=2
        )

        test_domain.repository_for(Person)._dao.update(person, age=10)
        u_person = test_domain.repository_for(Person)._dao.get(2)
        assert u_person is not None
        assert u_person.age == 10

    def test_updating_record_with_both_dictionary_args_and_kwargs(self, test_domain):
        """Update an existing entity in the repository"""
        person = test_domain.repository_for(Person)._dao.create(
            id=2, first_name="Johnny", last_name="John", age=2
        )

        test_domain.repository_for(Person)._dao.update(
            person, {"first_name": "Stephen"}, age=10
        )
        u_person = test_domain.repository_for(Person)._dao.get(2)
        assert u_person is not None
        assert u_person.age == 10
        assert u_person.first_name == "Stephen"

    def test_updating_record_through_filter(self, test_domain):
        """Test that update by query updates only correct records"""
        test_domain.repository_for(Person)._dao.create(
            id=1, first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.repository_for(Person)._dao.create(
            id=2, first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.repository_for(Person)._dao.create(
            id=3, first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.repository_for(Person)._dao.create(
            id=4, first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = (
            test_domain.repository_for(Person)
            ._dao.query.filter(age__gt=3)
            .update(last_name="Fraud")
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.repository_for(Person)._dao.get(1)
        u_person2 = test_domain.repository_for(Person)._dao.get(2)
        u_person3 = test_domain.repository_for(Person)._dao.get(3)
        u_person4 = test_domain.repository_for(Person)._dao.get(4)
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"

    def test_updating_multiple_records_through_filter_with_arg_value(self, test_domain):
        """Try updating all records satisfying filter in one step, passing a dict"""
        test_domain.repository_for(Person)._dao.create(
            id=1, first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.repository_for(Person)._dao.create(
            id=2, first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.repository_for(Person)._dao.create(
            id=3, first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.repository_for(Person)._dao.create(
            id=4, first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = test_domain.repository_for(Person)._dao._update_all(
            Q(age__gt=3), {"last_name": "Fraud"}
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.repository_for(Person)._dao.get(1)
        u_person2 = test_domain.repository_for(Person)._dao.get(2)
        u_person3 = test_domain.repository_for(Person)._dao.get(3)
        u_person4 = test_domain.repository_for(Person)._dao.get(4)
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"

    def test_updating_multiple_records_through_filter_with_kwarg_value(
        self, test_domain
    ):
        """Try updating all records satisfying filter in one step"""
        test_domain.repository_for(Person)._dao.create(
            id=1, first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.repository_for(Person)._dao.create(
            id=2, first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.repository_for(Person)._dao.create(
            id=3, first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.repository_for(Person)._dao.create(
            id=4, first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = test_domain.repository_for(Person)._dao._update_all(
            Q(age__gt=3), last_name="Fraud"
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.repository_for(Person)._dao.get(1)
        u_person2 = test_domain.repository_for(Person)._dao.get(2)
        u_person3 = test_domain.repository_for(Person)._dao.get(3)
        u_person4 = test_domain.repository_for(Person)._dao.get(4)
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"


class TestUpdateDeprecationWarning:
    """`DAO.update()` and `QuerySet.update()` are the patch-and-persist path,
    deprecated in 0.18.0 and removed in 1.0.0. Each must warn, name the
    replacement and the removal version, and a bulk `QuerySet.update()` must
    warn exactly once for the whole call, not once per matched row."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, part_of=Person)

    def test_dao_update_warns_naming_removal_and_replacement(self, test_domain):
        dao = test_domain.repository_for(Person)._dao
        person = dao.create(id=1, first_name="John", last_name="Doe", age=22)

        with pytest.warns(RemovedInProtean10Warning, match=r"v1\.0\.0") as record:
            dao.update(person, age=10)

        assert len(record) == 1
        message = str(record[0].message)
        assert "repository.add()" in message
        # Behaviour is unchanged: the patch is applied and persisted.
        assert dao.get(1).age == 10

    def test_queryset_update_warns_naming_removal_and_replacement(self, test_domain):
        dao = test_domain.repository_for(Person)._dao
        dao.create(id=1, first_name="John", last_name="Doe", age=22)

        with pytest.warns(RemovedInProtean10Warning, match=r"v1\.0\.0") as record:
            dao.query.filter(id=1).update(age=10)

        messages = [str(w.message) for w in record]
        assert any("UnitOfWork" in m for m in messages)
        assert dao.get(1).age == 10

    def test_bulk_queryset_update_warns_exactly_once(self, test_domain):
        """A bulk update over several matched rows drives the silent internal
        path per row, so the whole call emits exactly one warning, not N+1."""
        dao = test_domain.repository_for(Person)._dao
        for i in range(1, 4):
            dao.create(id=i, first_name=f"P{i}", last_name="Musketeer", age=i)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            updated_count = dao.query.filter(last_name="Musketeer").update(
                last_name="Fraud"
            )

        assert updated_count == 3
        queryset_warnings = [
            w for w in caught if issubclass(w.category, RemovedInProtean10Warning)
        ]
        assert len(queryset_warnings) == 1, (
            f"expected exactly one deprecation warning for a bulk update, "
            f"got {len(queryset_warnings)}"
        )
