import pytest

from protean.adapters.repository.sqlalchemy import SqlalchemyModel

from .elements import (
    ComplexUser,
    Email,
    Person,
    Provider,
    ProviderCustomModel,
    Receiver,
)


@pytest.mark.postgresql
class TestModel:
    @pytest.fixture(autouse=True)
    def register_person_aggregate(self, test_domain):
        test_domain.register(Person)

    def test_that_model_class_is_created_automatically(self, test_domain):
        database_model_cls = test_domain.repository_for(Person)._database_model
        assert issubclass(database_model_cls, SqlalchemyModel)
        assert database_model_cls.__name__ == "PersonModel"

    def test_conversation_from_entity_to_model(self, test_domain):
        database_model_cls = test_domain.repository_for(Person)._database_model
        person = Person(first_name="John", last_name="Doe")
        person_model_obj = database_model_cls.from_entity(person)

        assert person_model_obj is not None
        assert isinstance(person_model_obj, SqlalchemyModel)
        assert person_model_obj.age == 21
        assert person_model_obj.first_name == "John"
        assert person_model_obj.last_name == "Doe"

    def test_conversation_from_model_to_entity(self, test_domain):
        database_model_cls = test_domain.repository_for(Person)._database_model
        person = Person(first_name="John", last_name="Doe")
        person_model_obj = database_model_cls.from_entity(person)

        person_copy = database_model_cls.to_entity(person_model_obj)
        assert person_copy is not None

    def test_dynamically_constructed_model_attributes(self, test_domain):
        from sqlalchemy import String

        database_model_cls = test_domain.repository_for(Person)._database_model

        assert database_model_cls.__name__ == "PersonModel"
        assert type(database_model_cls.first_name.type) is String


@pytest.mark.postgresql
class TestModelWithVO:
    @pytest.fixture(autouse=True)
    def register_complex_user_aggregate(self, test_domain):
        test_domain.register(ComplexUser)

    def test_that_model_class_is_created_automatically(self, test_domain):
        database_model_cls = test_domain.repository_for(ComplexUser)._database_model
        assert issubclass(database_model_cls, SqlalchemyModel)
        assert database_model_cls.__name__ == "ComplexUserModel"

    def test_conversation_from_entity_to_model(self, test_domain):
        database_model_cls = test_domain.repository_for(ComplexUser)._database_model

        user1 = ComplexUser(email_address="john.doe@gmail.com", password="d4e5r6")
        user2 = ComplexUser(
            email=Email(address="john.doe@gmail.com"), password="d4e5r6"
        )

        user1_model_obj = database_model_cls.from_entity(user1)
        user2_model_obj = database_model_cls.from_entity(user2)

        assert user1_model_obj is not None
        assert isinstance(user1_model_obj, SqlalchemyModel)
        assert user1_model_obj.email_address == "john.doe@gmail.com"
        assert user1_model_obj.password == "d4e5r6"

        assert user2_model_obj is not None
        assert isinstance(user2_model_obj, SqlalchemyModel)
        assert user2_model_obj.email_address == "john.doe@gmail.com"
        assert user2_model_obj.password == "d4e5r6"

        # Model's content should reflect only the attributes, not declared_fields
        assert hasattr(user1_model_obj, "email") is False
        assert hasattr(user2_model_obj, "email") is False

    def test_conversation_from_model_to_entity(self, test_domain):
        database_model_cls = test_domain.repository_for(ComplexUser)._database_model
        user1 = ComplexUser(email_address="john.doe@gmail.com", password="d4e5r6")
        user1_model_obj = database_model_cls.from_entity(user1)

        user_copy = database_model_cls.to_entity(user1_model_obj)
        assert user_copy is not None


@pytest.mark.postgresql
class TestCustomModel:
    def test_that_custom_model_can_be_associated_with_entity(self, test_domain):
        test_domain.register(
            ProviderCustomModel, part_of=Provider, schema_name="adults"
        )
        database_model_cls = test_domain.repository_for(Provider)._database_model
        assert database_model_cls.__name__ == "ProviderCustomModel"

    def test_that_model_can_be_registered_with_domain_annotation(self, test_domain):
        from sqlalchemy import Column, Text

        test_domain.register(Receiver)

        @test_domain.database_model(part_of=Receiver)
        class ReceiverInlineModel:
            name = Column(Text)

        test_domain.repository_for(Receiver)._dao  # Registers and refreshes DB objects

        default_provider = test_domain.providers["default"]
        default_provider._metadata.create_all(default_provider._engine)

        database_model_cls = test_domain.repository_for(Receiver)._database_model
        assert database_model_cls.__name__ == "ReceiverInlineModel"

        assert type(database_model_cls.name.type) is Text
