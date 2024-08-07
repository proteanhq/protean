from collections import OrderedDict
from datetime import datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import NotSupportedError, ValidationError
from protean.utils import fully_qualified_name
from protean.utils.reflection import attributes, declared_fields

from .elements import (
    AccountWithId,
    Comment,
    ConcreteRole,
    Person,
    Post,
    ProfileWithAccountId,
    Role,
    SubclassRole,
)


class TestAggregateStructure:
    def test_that_base_aggregate_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError) as exc:
            BaseAggregate()

        assert str(exc.value) == "BaseAggregate cannot be instantiated"

    def test_aggregate_inheritance(self):
        assert issubclass(Role, BaseEntity)

    def test_successful_aggregate_registration(self, test_domain):
        test_domain.register(Role)
        assert fully_qualified_name(Role) in test_domain.registry.aggregates

    def test_field_definitions_declared_in_aggregate(self):
        declared_fields_keys = list(
            OrderedDict(sorted(declared_fields(Role).items())).keys()
        )
        assert declared_fields_keys == ["created_on", "id", "name"]

    def test_declared_reference_fields_in_an_aggregate(self, test_domain):
        declared_fields_keys = list(
            OrderedDict(sorted(declared_fields(Post).items())).keys()
        )
        assert declared_fields_keys == ["author", "comments", "content", "id"]

    def test_declared_has_one_fields_in_an_aggregate(self, test_domain):
        # `author` is a HasOne field, so it should be:
        #   absent in attributes
        #   present as `author` in declared_fields
        assert all(
            key in declared_fields(AccountWithId)
            for key in ["author", "email", "id", "password"]
        )
        assert all(
            key in attributes(AccountWithId) for key in ["email", "id", "password"]
        )
        assert "author" not in attributes(AccountWithId)

        # `account` is a Reference field, so it should be present as:
        #   `account_id` in attributes
        #   `account` in declared_fields
        assert all(
            key in declared_fields(ProfileWithAccountId)
            for key in ["about_me", "account"]
        )
        assert all(
            key in attributes(ProfileWithAccountId)
            for key in ["about_me", "account_id"]
        )

    def test_declared_has_many_fields_in_an_aggregate(self, test_domain):
        # `comments` is a HasMany field, so it should be:
        #   absent in attributes
        #   present as `comments` in declared_fields
        assert all(
            key in declared_fields(Post)
            for key in ["comments", "content", "id", "author"]
        )
        assert all(key in attributes(Post) for key in ["content", "id", "author_id"])
        assert "comments" not in attributes(Post)

        # `post` is a Reference field, so it should be present as:
        #   `post_id` in attributes
        #   `post` in declared_fields
        assert all(
            key in declared_fields(Comment)
            for key in ["added_on", "content", "id", "post"]
        )
        assert all(
            key in attributes(Comment)
            for key in ["added_on", "content", "id", "post_id"]
        )


class TestSubclassedAggregateStructure:
    def test_subclass_aggregate_field_definitions(self):
        declared_fields_keys = list(
            OrderedDict(sorted(declared_fields(SubclassRole).items())).keys()
        )
        assert declared_fields_keys == ["created_on", "id", "name"]

    def test_that_fields_in_base_classes_are_inherited(self):
        declared_fields_keys = list(
            OrderedDict(sorted(declared_fields(ConcreteRole).items())).keys()
        )
        assert declared_fields_keys == ["bar", "foo", "id"]

        role = ConcreteRole(id=3, foo="foo", bar="bar")
        assert role is not None
        assert role.foo == "foo"


class TestAggregateInitialization:
    def test_successful_aggregate_initialization(self):
        role = Role(name="ADMIN")
        assert role is not None
        assert role.name == "ADMIN"
        assert type(role.created_on) is datetime

    def test_individuality(self):
        """Test successful Account Entity initialization"""

        role1 = Role(name="ADMIN")
        role2 = Role(name="USER")
        assert role1.name == "ADMIN"
        assert role2.name == "USER"

    def test_initialization_from_dict_template(self):
        with pytest.raises(AssertionError):
            Person("John Doe")

        person = Person({"first_name": "John", "last_name": "Doe", "age": 23})
        assert person.first_name == "John"
        assert person.last_name == "Doe"
        assert person.age == 23

    def test_template_param_is_a_dict(self):
        with pytest.raises(AssertionError) as exc:
            Person(["John", "Doe", 23])

        assert str(exc.value) == (
            "Positional argument ['John', 'Doe', 23] passed must be a dict. "
            "This argument serves as a template for loading common values."
        )

    def test_error_message_content_on_validation_error(self):
        # Single error message
        try:
            Person(last_name="Doe")
        except ValidationError as err:
            assert err.messages == {"first_name": ["is required"]}

        # Test multiple error messages
        try:
            Person(last_name="Doe", age="old")
        except ValidationError as err:
            assert err.messages == {
                "first_name": ["is required"],
                "age": ['"old" value must be an integer.'],
            }


class TestAggregateFieldValues:
    def test_that_validation_error_is_raised_if_required_fields_are_not_provided(self):
        with pytest.raises(ValidationError):
            Role(id=123423)

    def test_that_field_values_are_defaulted_when_not_provided(self):
        """Test that values are defaulted properly"""
        person = Person(first_name="John", last_name="Doe")
        assert person.age == 21

    def test_that_field_values_with_default_settings_can_be_specified_explicitly(self):
        """Test that values are defaulted properly"""
        person = Person(first_name="John", last_name="Doe", age=35)
        assert person.age == 35

    def test_that_validation_error_is_raised_when_specified_string_length_is_breached(
        self,
    ):
        """Test validation of String length checks"""
        with pytest.raises(ValidationError):
            Role(name="THIS_IS_A_VERY_LONG_ROLE_NAME")

    def test_that_values_are_validated_against_specified_data_types(self):
        """Test validation of data types of values"""
        with pytest.raises(ValidationError):
            Person(first_name="John", age="Young")
