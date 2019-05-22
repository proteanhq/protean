import pytest

from protean.core.exceptions import InvalidOperationError

from .elements import Email, MyOrgEmail


class TestEquivalence:
    def test_two_value_objects_with_equal_values_are_considered_equal(self):
        email1 = Email.from_address('john.doe@gmail.com')
        email2 = Email.from_address('john.doe@gmail.com')

        assert email1 == email2

    def test_that_two_value_objects_with_different_values_are_different(self):
        email3 = Email.from_address('john.doe@gmail.com')
        email4 = Email.from_address('jane.doe@gmail.com')

        assert email3 != email4

    def test_that_two_value_objects_of_inherited_types_are_different_even_with_same_values(self):
        email = Email.from_address('john.doe@gmail.com')
        my_org_email = MyOrgEmail.from_address('john.doe@gmail.com')

        assert email != my_org_email

    def test_generated_value_object_hash(self):
        """Test that the entity's hash is based on its identity"""
        hashed_value = hash(frozenset({'address': 'john.doe@gmail.com'}.items()))

        email = Email.from_address('john.doe@gmail.com')
        assert hash(email) == hashed_value

    def test_that_two_value_objects_that_are_equal_have_equal_hash(self):
        email1 = Email.from_address('john.doe@gmail.com')
        email2 = Email.from_address('john.doe@gmail.com')

        assert email1 == email2
        assert hash(email1) == hash(email2)


class TestProperties:
    def test_output_to_dict(self):
        pass

    def test_repr_output_of_value_object(self):
        pass

    def test_that_value_objects_are_immutable(self):
        email = Email.from_address(address='john.doe@gmail.com')
        with pytest.raises(InvalidOperationError):
            email.local_part = 'jane.doe'


class TestEmailVOStructure:
    def test_email_vo_has_address_field(self):
        assert len(Email.meta_.declared_fields) == 1
        assert 'address' in Email.meta_.declared_fields


class TestEmailVOBehavior:
    def test_validity(self):
        assert Email.validate('john.doe@gmail.com')
        assert not Email.validate('john.doe')
        assert not Email.validate('1234567890@gmail.com' * 26)

        with pytest.raises(ValueError):
            Email.from_address('john.doe')

    def test_init_from_constructor(self):
        email = Email(local_part='john.doe', domain_part='gmail.com')
        assert email is not None
        assert email.local_part == 'john.doe'
        assert email.domain_part == 'gmail.com'

    def test_init_from_parts(self):
        email = Email.from_parts('john.doe', 'gmail.com')
        assert email is not None
        assert email.local_part == 'john.doe'
        assert email.domain_part == 'gmail.com'

    def test_init_build(self):
        email = Email.from_address('john.doe@gmail.com')
        assert email is not None
        assert email.local_part == 'john.doe'
        assert email.domain_part == 'gmail.com'
