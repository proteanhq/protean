import pytest

from protean.adapters.repository.elasticsearch import ElasticsearchModel

from .elements import (
    ComplexUser,
    Email,
    Person,
    Provider,
    ProviderCustomModel,
    Receiver,
)


@pytest.mark.elasticsearch
class TestDefaultModel:
    @pytest.fixture(autouse=True)
    def register_person_aggregate(self, test_domain):
        test_domain.register(Person)

    def test_that_model_class_is_created_automatically(self, test_domain):
        model_cls = test_domain.get_model(Person)
        assert issubclass(model_cls, ElasticsearchModel)
        assert model_cls.__name__ == "PersonModel"

    def test_conversation_from_entity_to_model(self, test_domain):
        model_cls = test_domain.get_model(Person)
        person = Person(first_name="John", last_name="Doe")
        person_model_obj = model_cls.from_entity(person)

        assert person_model_obj is not None
        assert isinstance(person_model_obj, ElasticsearchModel)
        assert person_model_obj.age == 21
        assert person_model_obj.first_name == "John"
        assert person_model_obj.last_name == "Doe"

        # The ID attribute for an Elasticsearch model will be in model_obj.meta.id
        assert person_model_obj.meta.id is not None
        assert person_model_obj.meta.id == person.id

    def test_conversation_from_model_to_entity(self, test_domain):
        model_cls = test_domain.get_model(Person)
        person = Person(first_name="John", last_name="Doe")
        person_model_obj = model_cls.from_entity(person)

        person_copy = model_cls.to_entity(person_model_obj)
        assert person_copy is not None

        assert person_copy.id == person_model_obj.meta.id

    def test_dynamically_constructed_model_attributes(self, test_domain):
        from elasticsearch_dsl import Index

        test_domain.register(Receiver)

        # Ensure that index is created for `Receiver` - START
        provider = test_domain.get_provider("default")
        conn = provider.get_connection()

        for _, aggregate_record in test_domain.registry.aggregates.items():
            index = Index(aggregate_record.cls.meta_.schema_name, using=conn)
            if not index.exists():
                index.create()
        # Ensure that index is created for `Receiver` - END

        model_cls = test_domain.get_model(Receiver)
        assert model_cls.__name__ == "ReceiverModel"

        # FIXME Verify default constructed fields
        # assert model_cls.name._params is None


@pytest.mark.elasticsearch
class TestModelWithVO:
    @pytest.fixture(autouse=True)
    def register_complex_user_aggregate(self, test_domain):
        test_domain.register(ComplexUser)

    def test_that_model_class_is_created_automatically(self, test_domain):
        model_cls = test_domain.get_model(ComplexUser)
        assert issubclass(model_cls, ElasticsearchModel)
        assert model_cls.__name__ == "ComplexUserModel"

    def test_conversation_from_entity_to_model(self, test_domain):
        model_cls = test_domain.get_model(ComplexUser)

        user1 = ComplexUser(email_address="john.doe@gmail.com", password="d4e5r6")
        user2 = ComplexUser(
            email=Email(address="john.doe@gmail.com"), password="d4e5r6"
        )

        user1_model_obj = model_cls.from_entity(user1)
        user2_model_obj = model_cls.from_entity(user2)

        assert user1_model_obj is not None
        assert isinstance(user1_model_obj, ElasticsearchModel)
        assert user1_model_obj.email_address == "john.doe@gmail.com"
        assert user1_model_obj.password == "d4e5r6"

        assert user2_model_obj is not None
        assert isinstance(user2_model_obj, ElasticsearchModel)
        assert user2_model_obj.email_address == "john.doe@gmail.com"
        assert user2_model_obj.password == "d4e5r6"

        # Model's content should reflect only the attributes, not declared_fields
        # Model's content should reflect only the attributes, not declared_fields
        assert hasattr(user1_model_obj, "email") is False
        assert hasattr(user2_model_obj, "email") is False

    def test_conversation_from_model_to_entity(self, test_domain):
        model_cls = test_domain.get_model(ComplexUser)
        user1 = ComplexUser(email_address="john.doe@gmail.com", password="d4e5r6")
        user1_model_obj = model_cls.from_entity(user1)

        user_copy = model_cls.to_entity(user1_model_obj)
        assert user_copy is not None


@pytest.mark.elasticsearch
class TestCustomModel:
    def test_that_custom_model_can_be_associated_with_entity(self, test_domain):
        test_domain.register(Provider)
        test_domain.register_model(ProviderCustomModel, entity_cls=Provider)

        model_cls = test_domain.get_model(Provider)
        assert model_cls.__name__ == "ProviderCustomModel"

    def test_that_custom_model_is_persisted_via_dao(self, test_domain):
        test_domain.register(Provider)
        test_domain.register_model(ProviderCustomModel, entity_cls=Provider)

        provider_dao = test_domain.get_dao(Provider)
        provider = provider_dao.create(name="John", about="Me, Myself, and Jane")
        assert provider is not None

    def test_that_custom_model_is_retrievable_via_dao(self, test_domain):
        test_domain.register(Provider)
        test_domain.register_model(ProviderCustomModel, entity_cls=Provider)

        provider_dao = test_domain.get_dao(Provider)
        provider = provider_dao.create(name="John", about="Me, Myself, and Jane")

        provider = provider_dao.get(provider.id)
        assert provider is not None
        assert provider.name == "John"

    def test_that_model_can_be_registered_with_domain_annotation(self, test_domain):
        from elasticsearch_dsl import Index, Keyword, Text

        test_domain.register(Receiver)

        @test_domain.model(entity_cls=Receiver)
        class ReceiverInlineModel:
            name = Text(fields={"raw": Keyword()})

        # Ensure that index is created for `Receiver` - START
        provider = test_domain.get_provider("default")
        conn = provider.get_connection()

        for _, aggregate_record in test_domain.registry.aggregates.items():
            index = Index(aggregate_record.cls.meta_.schema_name, using=conn)
            if not index.exists():
                index.create()
        # Ensure that index is created for `Receiver` - END

        model_cls = test_domain.get_model(Receiver)
        assert model_cls.__name__ == "ReceiverInlineModel"
        assert model_cls.name._params["fields"] == {"raw": Keyword()}

    def test_persistence_via_model_registered_with_domain_annotation(self, test_domain):
        from elasticsearch_dsl import Keyword, Text

        test_domain.register(Receiver)

        @test_domain.model(entity_cls=Receiver)
        class ReceiverInlineModel(ElasticsearchModel):
            name = Text(fields={"raw": Keyword()})

        test_domain.register(Provider)
        test_domain.register_model(ProviderCustomModel, entity_cls=Provider)

        provider_dao = test_domain.get_dao(Provider)
        provider = provider_dao.create(name="John", about="Me, Myself, and Jane")

        provider = provider_dao.get(provider.id)
        assert provider is not None
        assert provider.name == "John"

        receiver_dao = test_domain.get_dao(Receiver)
        receiver = receiver_dao.create(name="John")

        receiver = receiver_dao.get(receiver.id)
        assert receiver is not None
        assert receiver.name == "John"
