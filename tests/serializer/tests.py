import pytest

from protean.core.field.basic import Integer, String
from protean.core.serializer import BaseSerializer
from protean.utils import fully_qualified_name

from .elements import User, UserSchema


class TestSerializerInitialization:
    def test_that_base_serializer_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseSerializer()

    def test_that_a_concrete_serializer_can_be_instantiated(self):
        schema = UserSchema()
        assert schema is not None

    def test_that_meta_is_loaded_with_attributes(self):
        assert UserSchema.meta_.aggregate_cls is not None
        assert UserSchema.meta_.aggregate_cls == User

        assert UserSchema.meta_.declared_fields is not None
        assert all(key in UserSchema.meta_.declared_fields for key in ["name", "age"])


class TestSerializerRegistration:
    def test_that_serializer_can_be_registered_with_domain(self, test_domain):
        test_domain.register(UserSchema)

        assert fully_qualified_name(UserSchema) in test_domain.registry.serializers

    def test_that_serializer_can_be_registered_via_annotations(self, test_domain):
        @test_domain.serializer
        class PersonSchema:
            name = String(required=True)
            age = Integer(required=True)

            class Meta:
                aggregate_cls = User

        assert fully_qualified_name(PersonSchema) in test_domain.registry.serializers


class TestSerializerDump:
    def test_that_serializer_dumps_data_from_domain_element(self):
        user = User(name="John Doe", age=24)
        json_result = UserSchema().dump(user)
        assert json_result == {"age": 24, "name": "John Doe"}
