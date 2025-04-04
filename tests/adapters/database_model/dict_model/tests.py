import pytest

from protean.adapters.repository.memory import MemoryModel
from protean.fields import Text

from .elements import Email, Person, Provider, ProviderCustomModel, Receiver, User


class TestDatabaseModel:
    @pytest.fixture(autouse=True)
    def register_person_aggregate(self, test_domain):
        test_domain.register(Person)
        test_domain.init(traverse=False)

    def test_that_db_model_class_is_created_automatically(self, test_domain):
        database_model_cls = test_domain.repository_for(Person)._database_model
        assert issubclass(database_model_cls, MemoryModel)
        assert database_model_cls.__name__ == "PersonModel"

    def test_conversion_from_entity_to_model(self, test_domain):
        database_model_cls = test_domain.repository_for(Person)._database_model

        person = Person(first_name="John", last_name="Doe")

        person_model_obj = database_model_cls.from_entity(person)

        assert person_model_obj is not None
        assert isinstance(person_model_obj, dict)
        assert person_model_obj["age"] == 21
        assert person_model_obj["first_name"] == "John"
        assert person_model_obj["last_name"] == "Doe"

    def test_conversion_from_model_to_entity(self, test_domain):
        database_model_cls = test_domain.repository_for(Person)._database_model
        person = Person(first_name="John", last_name="Doe")
        person_model_obj = database_model_cls.from_entity(person)

        person_copy = database_model_cls.to_entity(person_model_obj)
        assert person_copy is not None


class TestModelWithVO:
    @pytest.fixture(autouse=True)
    def register_user_aggregate(self, test_domain):
        test_domain.register(User)

    def test_that_db_model_class_is_created_automatically(self, test_domain):
        database_model_cls = test_domain.repository_for(User)._database_model
        assert issubclass(database_model_cls, MemoryModel)
        assert database_model_cls.__name__ == "UserModel"

    def test_conversion_from_entity_to_model(self, test_domain):
        database_model_cls = test_domain.repository_for(User)._database_model

        user1 = User(email_address="john.doe@gmail.com", password="d4e5r6")
        user2 = User(email=Email(address="john.doe@gmail.com"), password="d4e5r6")

        user1_model_obj = database_model_cls.from_entity(user1)
        user2_model_obj = database_model_cls.from_entity(user2)

        assert user1_model_obj is not None
        assert isinstance(user1_model_obj, dict)
        assert user1_model_obj["email_address"] == "john.doe@gmail.com"
        assert user1_model_obj["password"] == "d4e5r6"

        assert user2_model_obj is not None
        assert isinstance(user2_model_obj, dict)
        assert user2_model_obj["email_address"] == "john.doe@gmail.com"
        assert user2_model_obj["password"] == "d4e5r6"

        # Model's content should reflect only the attributes, not declared_fields
        assert "email" not in user1_model_obj
        assert "email" not in user2_model_obj

    def test_conversion_from_model_to_entity(self, test_domain):
        database_model_cls = test_domain.repository_for(User)._database_model
        user1 = User(email_address="john.doe@gmail.com", password="d4e5r6")
        user1_model_obj = database_model_cls.from_entity(user1)

        user_copy = database_model_cls.to_entity(user1_model_obj)
        assert user_copy is not None
        assert user_copy.id == user1_model_obj["id"]


class TestCustomModel:
    def test_that_custom_model_is_associated_with_entity(self, test_domain):
        test_domain.register(Provider)
        test_domain.register(
            ProviderCustomModel, part_of=Provider, schema_name="adults"
        )

        assert (
            test_domain.repository_for(Provider)._database_model.__name__
            == "ProviderCustomModel"
        )

    def test_that_db_model_can_be_registered_with_domain_annotation(self, test_domain):
        from protean.fields import Text

        test_domain.register(Receiver)

        @test_domain.database_model(part_of=Receiver)
        class ReceiverInlineModel:
            about = Text()

        database_model_cls = test_domain.repository_for(Receiver)._database_model

        assert database_model_cls.__name__ == "ReceiverInlineModel"

        # FIXME This test will fail in the future
        #   when models are validated for fields to be present in corresponding entities/aggregates
        assert hasattr(database_model_cls, "about")

    def test_explicit_model_is_returned_if_provided(self, test_domain):
        class ProviderCustomMemoryModel(MemoryModel):
            name = Text()

        test_domain.register(Provider)
        test_domain.register(
            ProviderCustomMemoryModel, part_of=Provider, schema_name="adults"
        )

        assert (
            test_domain.repository_for(Provider)._database_model
            is ProviderCustomMemoryModel
        )
