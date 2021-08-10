from datetime import datetime
from uuid import UUID, uuid4

import pytest

from protean.core.field.basic import Auto, String
from protean.exceptions import InvalidOperationError, ValidationError

from .elements import PersonAutoSSN, PersonExplicitID, Role, SubclassRole


class TestProperties:
    def test_conversion_of_aggregate_values_to_dict(self):
        current_time = datetime.now()
        role = Role(id=12, name="ADMIN", created_on=current_time)
        assert role.to_dict() == {
            "id": 12,
            "name": "ADMIN",
            "created_on": str(current_time),
        }

    def test_repr_output_of_aggregate(self):
        role = Role(id=12, name="ADMIN")

        assert str(role) == "Role object (id: 12)"
        assert repr(role) == "<Role: Role object (id: 12)>"


class TestIdentity:
    """Grouping of Identity related test cases"""

    def test_id_field_in_meta(self):
        assert hasattr(Role.meta_, "id_field")
        assert type(Role.meta_.id_field) is Auto

    def test_default_id_field_construction(self):
        assert "id" in Role.meta_.declared_fields
        assert "id" in Role.meta_.attributes

        assert type(Role.meta_.declared_fields["id"]) is Auto
        assert Role.meta_.id_field == Role.meta_.declared_fields["id"]

    def test_non_default_auto_id_field_construction(self):
        assert "id" not in PersonAutoSSN.meta_.declared_fields
        assert "id" not in PersonAutoSSN.meta_.attributes

        assert type(PersonAutoSSN.meta_.declared_fields["ssn"]) is Auto
        assert PersonAutoSSN.meta_.id_field.field_name == "ssn"
        assert (
            PersonAutoSSN.meta_.id_field == PersonAutoSSN.meta_.declared_fields["ssn"]
        )

    def test_non_default_explicit_id_field_construction(self, test_domain):
        assert "id" not in PersonExplicitID.meta_.declared_fields
        assert "id" not in PersonExplicitID.meta_.attributes

        assert type(PersonExplicitID.meta_.declared_fields["ssn"]) is String
        assert PersonExplicitID.meta_.id_field.field_name == "ssn"
        assert (
            PersonExplicitID.meta_.id_field
            == PersonExplicitID.meta_.declared_fields["ssn"]
        )


class TestIdentityValues:
    """Grouping of Identity value related test cases"""

    def test_default_id_field_value(self):
        role = Role(name="ADMIN")
        assert role.id is not None

        try:
            uuid_obj = UUID(str(role.id))
        except ValueError:
            pytest.fail("ID is not valid UUID")

        assert str(uuid_obj) == role.id

    def test_that_ids_are_immutable(self):
        """Test that `id` cannot be changed once assigned"""
        role = Role(id=12, name="ADMIN")

        with pytest.raises(InvalidOperationError):
            role.id = 13

    def test_non_default_auto_id_field_value(self):
        role = PersonAutoSSN(name="John Doe")
        assert role.ssn is not None

        try:
            uuid_obj = UUID(str(role.ssn))
        except ValueError:
            pytest.fail("SSN is not valid UUID")

        assert str(uuid_obj) == role.ssn

    def test_non_default_explicit_id_field_value(self):
        with pytest.raises(ValidationError):
            role = PersonExplicitID(name="John Doe")

        new_uuid = uuid4()
        role = PersonExplicitID(ssn=new_uuid, name="John Doe")
        assert role is not None
        assert role.ssn == str(new_uuid)

    def test_that_explicit_id_can_be_supplied_to_auto_id_field(self):
        new_uuid = uuid4()
        role = Role(id=new_uuid, name="ADMIN")
        assert role.id is not None
        assert role.id == new_uuid


class TestEquivalence:
    def test_that_two_entities_with_same_id_are_treated_as_equal(self):
        role1 = Role(id=12345, name="ADMIN1")
        role2 = Role(id=12346, name="ADMIN1")

        assert role1 != role2  # Because their identities are different
        assert role2 != role1  # Because their identities are different

        role3 = Role(id=12345, name="ADMIN1")
        assert (
            role1 == role3
        )  # Because it's the same record even though attributes differ
        assert role3 == role1

    def test_that_two_entities_of_different_types_are_different_even_with_same_id(self):
        """Test that two entities are not considered equal even if they have the same ID
            and one belongs to a different Entity class
        """
        role = Role(id=1, name="ADMIN")
        person = PersonAutoSSN(id=1, name="ADMIN")

        assert role != person  # Even though their identities are the same
        assert person != role  # Even though their identities are the same

    def test_that_two_entities_of_inherited_types_are_different_even_with_same_id(self):
        """Test that two entities are not considered equal even if they have the same ID
            and one is subclassed from the other
        """
        role = Role(id=1, name="ADMIN")
        subclass_role = SubclassRole(id=1, name="ADMIN")

        assert role != subclass_role  # Even though their identities are the same
        assert subclass_role != role  # Even though their identities are the same

    def test_generated_aggregate_hash(self):
        """Test that the entity's hash is based on its identity"""
        hashed_id = hash(1)

        role = Role(id=1, name="ADMIN")
        assert hashed_id == hash(
            role
        )  # FIXME Should hash be based on ID alone, or other attrs too?

    def test_that_two_aggregates_that_are_equal_have_equal_hash(self):
        role1 = Role(id=12345, name="ADMIN1")
        role2 = Role(id=12345, name="ADMIN1")

        assert hash(role1) == hash(role2)
