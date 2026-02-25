"""Generic bulk operation tests that run against all database providers.

Covers update_all(), delete_all(), and filtered bulk operations
on the DAO layer.
"""

from datetime import datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import ObjectNotFoundError
from protean.fields import DateTime, Integer, String
from protean.utils.query import Q


class Person(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)
    created_at: DateTime(default=datetime.now())


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)


@pytest.mark.basic_storage
class TestBulkDeleteOperations:
    def test_delete_all_records_in_repository(self, test_domain):
        """Delete all objects in a repository"""
        test_domain.repository_for(Person)._dao.create(
            id="1", first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="dArtagnan", last_name="Musketeer", age=5
        )

        person_records = test_domain.repository_for(Person)._dao.query.filter(Q())
        assert person_records.total == 4

        test_domain.repository_for(Person)._dao.delete_all()

        person_records = test_domain.repository_for(Person)._dao.query.filter(Q())
        assert person_records.total == 0

    def test_deleting_all_entities_of_a_type(self, test_domain):
        test_domain.repository_for(Person)._dao.create(
            first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="dArtagnan", last_name="Musketeer", age=5
        )

        people = test_domain.repository_for(Person)._dao.query.all()
        assert people.total == 4

        test_domain.repository_for(Person)._dao.delete_all()

        people = test_domain.repository_for(Person)._dao.query.all()
        assert people.total == 0

    def test_deleting_all_records_of_a_type_satisfying_a_filter(self, test_domain):
        person1 = test_domain.repository_for(Person)._dao.create(
            first_name="Athos", last_name="Musketeer", age=2
        )
        person2 = test_domain.repository_for(Person)._dao.create(
            first_name="Porthos", last_name="Musketeer", age=3
        )
        person3 = test_domain.repository_for(Person)._dao.create(
            first_name="Aramis", last_name="Musketeer", age=4
        )
        person4 = test_domain.repository_for(Person)._dao.create(
            first_name="d'Artagnan", last_name="Musketeer", age=5
        )

        # Perform update
        deleted_count = (
            test_domain.repository_for(Person)._dao.query.filter(age__gt=3).delete_all()
        )

        # Query and check if only the relevant records have been deleted
        assert deleted_count == 2

        refreshed_person1 = test_domain.repository_for(Person)._dao.get(person1.id)
        refreshed_person2 = test_domain.repository_for(Person)._dao.get(person2.id)

        assert refreshed_person1 is not None
        assert refreshed_person2 is not None

        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.get(person3.id)

        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.get(person4.id)

    def test_deleting_records_satisfying_a_filter(self, test_domain):
        person1 = test_domain.repository_for(Person)._dao.create(
            id="1", first_name="Athos", last_name="Musketeer", age=2
        )
        person2 = test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Porthos", last_name="Musketeer", age=3
        )
        person3 = test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Aramis", last_name="Musketeer", age=4
        )
        person4 = test_domain.repository_for(Person)._dao.create(
            id="4", first_name="d'Artagnan", last_name="Musketeer", age=5
        )

        # Perform delete
        deleted_count = (
            test_domain.repository_for(Person)._dao.query.filter(age__gt=3).delete()
        )

        # Query and check if only the relevant records have been deleted
        assert deleted_count == 2
        assert test_domain.repository_for(Person)._dao.query.all().total == 2

        assert test_domain.repository_for(Person)._dao.get(person1.id) is not None
        assert test_domain.repository_for(Person)._dao.get(person2.id) is not None
        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.get(person3.id)

        with pytest.raises(ObjectNotFoundError):
            test_domain.repository_for(Person)._dao.get(person4.id)


@pytest.mark.basic_storage
class TestBulkUpdateOperations:
    def test_updating_record_through_filter(self, test_domain):
        """Test that update by query updates only correct records"""
        test_domain.repository_for(Person)._dao.create(
            id="1", first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = (
            test_domain.repository_for(Person)
            ._dao.query.filter(age__gt=3)
            .update(last_name="Fraud")
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.repository_for(Person)._dao.get("1")
        u_person2 = test_domain.repository_for(Person)._dao.get("2")
        u_person3 = test_domain.repository_for(Person)._dao.get("3")
        u_person4 = test_domain.repository_for(Person)._dao.get("4")
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"

    def test_updating_multiple_records_through_filter_with_arg_value(self, test_domain):
        """Try updating all records satisfying filter in one step, passing a dict"""
        test_domain.repository_for(Person)._dao.create(
            id="1", first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = (
            test_domain.repository_for(Person)
            ._dao.query.filter(age__gt=3)
            .update_all({"last_name": "Fraud"})
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.repository_for(Person)._dao.get("1")
        u_person2 = test_domain.repository_for(Person)._dao.get("2")
        u_person3 = test_domain.repository_for(Person)._dao.get("3")
        u_person4 = test_domain.repository_for(Person)._dao.get("4")
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"

    def test_updating_multiple_records_through_filter_with_kwarg_value(
        self, test_domain
    ):
        """Try updating all records satisfying filter in one step"""
        test_domain.repository_for(Person)._dao.create(
            id="1", first_name="Athos", last_name="Musketeer", age=2
        )
        test_domain.repository_for(Person)._dao.create(
            id="2", first_name="Porthos", last_name="Musketeer", age=3
        )
        test_domain.repository_for(Person)._dao.create(
            id="3", first_name="Aramis", last_name="Musketeer", age=4
        )
        test_domain.repository_for(Person)._dao.create(
            id="4", first_name="dArtagnan", last_name="Musketeer", age=5
        )

        # Perform update
        updated_count = (
            test_domain.repository_for(Person)
            ._dao.query.filter(age__gt=3)
            .update_all(last_name="Fraud")
        )

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_person1 = test_domain.repository_for(Person)._dao.get("1")
        u_person2 = test_domain.repository_for(Person)._dao.get("2")
        u_person3 = test_domain.repository_for(Person)._dao.get("3")
        u_person4 = test_domain.repository_for(Person)._dao.get("4")
        assert u_person1.last_name == "Musketeer"
        assert u_person2.last_name == "Musketeer"
        assert u_person3.last_name == "Fraud"
        assert u_person4.last_name == "Fraud"
