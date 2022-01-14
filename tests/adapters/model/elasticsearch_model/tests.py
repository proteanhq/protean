import pytest

from elasticsearch_dsl import Keyword, Text

from protean import BaseAggregate
from protean.adapters.repository.elasticsearch import ElasticsearchModel
from protean.fields import String

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
        model_cls = test_domain.repository_for(Person)._model
        assert issubclass(model_cls, ElasticsearchModel)
        assert model_cls.__name__ == "PersonModel"

    def test_conversation_from_entity_to_model(self, test_domain):
        model_cls = test_domain.repository_for(Person)._model
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
        model_cls = test_domain.repository_for(Person)._model
        person = Person(first_name="John", last_name="Doe")
        person_model_obj = model_cls.from_entity(person)

        person_copy = model_cls.to_entity(person_model_obj)
        assert person_copy is not None

        assert person_copy.id == person_model_obj.meta.id

    def test_dynamically_constructed_model_attributes(self, test_domain):
        from elasticsearch_dsl import Index

        test_domain.register(Receiver)

        # Ensure that index is created for `Receiver` - START
        provider = test_domain.providers["default"]
        conn = provider.get_connection()

        for _, aggregate_record in test_domain.registry.aggregates.items():
            index = Index(aggregate_record.cls.meta_.schema_name, using=conn)
            if not index.exists():
                index.create()
        # Ensure that index is created for `Receiver` - END

        model_cls = test_domain.repository_for(Receiver)._model
        assert model_cls.__name__ == "ReceiverModel"

        # FIXME Verify default constructed fields
        # assert model_cls.name._params is None


@pytest.mark.elasticsearch
class TestModelOptions:
    class TestModelName:
        def test_default_generated_index_name(self, test_domain):
            class Person(BaseAggregate):
                name = String(max_length=50, required=True)
                about = Text()

            test_domain.register(Person)
            model_cls = test_domain.repository_for(Person)._model

            assert model_cls.__name__ == "PersonModel"
            assert model_cls._index._name == "person"

        def test_explicit_index_name(self, test_domain):
            class Person(BaseAggregate):
                name = String(max_length=50, required=True)
                about = Text()

                class Meta:
                    schema_name = "people"

            test_domain.register(Person)
            model_cls = test_domain.repository_for(Person)._model

            assert model_cls._index._name == "people"

        def test_explicit_index_name_in_custom_model(self, test_domain):
            class Person(BaseAggregate):
                name = String(max_length=50, required=True)
                about = Text()

            class PeopleModel(ElasticsearchModel):
                name = Text(fields={"raw": Keyword()})
                about = Text()

                class Index:
                    name = "people"

            test_domain.register(Person)
            test_domain.register_model(PeopleModel, entity_cls=Person)

            model_cls = test_domain.repository_for(Person)._model
            assert model_cls.__name__ == "PeopleModel"
            assert model_cls._index._name == "people"

    class TestModelNamespacePrefix:
        @pytest.fixture(autouse=True)
        def prefix_namespace(self, test_domain):
            test_domain.config["DATABASES"]["default"]["NAMESPACE_PREFIX"] = "foo"

        def test_generated_index_name_with_namespace_prefix(self, test_domain):
            class Person(BaseAggregate):
                name = String(max_length=50, required=True)
                about = Text()

            test_domain.register(Person)
            model_cls = test_domain.repository_for(Person)._model

            assert model_cls.__name__ == "PersonModel"
            assert model_cls._index._name == "foo_person"

        def test_generated_index_name_with_namespace_separator(self, test_domain):
            test_domain.config["DATABASES"]["default"]["NAMESPACE_SEPARATOR"] = "#"

            class Person(BaseAggregate):
                name = String(max_length=50, required=True)
                about = Text()

            test_domain.register(Person)
            model_cls = test_domain.repository_for(Person)._model

            assert model_cls.__name__ == "PersonModel"
            assert model_cls._index._name == "foo#person"

        def test_explicit_index_name_with_namespace_prefix(self, test_domain):
            class Person(BaseAggregate):
                name = String(max_length=50, required=True)
                about = Text()

                class Meta:
                    schema_name = "people"

            test_domain.register(Person)
            model_cls = test_domain.repository_for(Person)._model

            assert model_cls._index._name == "foo_people"

        def test_explicit_index_name_with_namespace_prefix_in_custom_model(
            self, test_domain
        ):
            class Person(BaseAggregate):
                name = String(max_length=50, required=True)
                about = Text()

            class PeopleModel(ElasticsearchModel):
                name = Text(fields={"raw": Keyword()})
                about = Text()

                class Index:
                    name = "custom-people"

            test_domain.register(Person)
            test_domain.register_model(PeopleModel, entity_cls=Person)

            model_cls = test_domain.repository_for(Person)._model
            assert model_cls.__name__ == "PeopleModel"
            assert model_cls._index._name == "custom-people"

    class TestModelSettings:
        @pytest.fixture(autouse=True)
        def attach_settings(self, test_domain):
            test_domain.config["DATABASES"]["default"]["SETTINGS"] = {
                "number_of_shards": 2
            }

        def test_provider_level_settings(self, test_domain):
            class Person(BaseAggregate):
                name = String(max_length=50, required=True)
                about = Text()

            test_domain.register(Person)
            model_cls = test_domain.repository_for(Person)._model

            assert model_cls._index._settings == {"number_of_shards": 2}

        def test_settings_override_in_custom_model(self, test_domain):
            class Person(BaseAggregate):
                name = String(max_length=50, required=True)
                about = Text()

            class PeopleModel(ElasticsearchModel):
                name = Text(fields={"raw": Keyword()})
                about = Text()

                class Index:
                    name = "people"
                    settings = {"number_of_shards": 2}

            test_domain.register(Person)
            test_domain.register_model(PeopleModel, entity_cls=Person)

            model_cls = test_domain.repository_for(Person)._model
            assert model_cls.__name__ == "PeopleModel"
            assert model_cls._index._name == "people"
            assert model_cls._index._settings == {"number_of_shards": 2}


@pytest.mark.elasticsearch
class TestModelWithVO:
    @pytest.fixture(autouse=True)
    def register_complex_user_aggregate(self, test_domain):
        test_domain.register(ComplexUser)

    def test_that_model_class_is_created_automatically(self, test_domain):
        model_cls = test_domain.repository_for(ComplexUser)._model
        assert issubclass(model_cls, ElasticsearchModel)
        assert model_cls.__name__ == "ComplexUserModel"

    def test_conversation_from_entity_to_model(self, test_domain):
        model_cls = test_domain.repository_for(ComplexUser)._model

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
        model_cls = test_domain.repository_for(ComplexUser)._model
        user1 = ComplexUser(email_address="john.doe@gmail.com", password="d4e5r6")
        user1_model_obj = model_cls.from_entity(user1)

        user_copy = model_cls.to_entity(user1_model_obj)
        assert user_copy is not None


@pytest.mark.elasticsearch
class TestCustomModel:
    def test_that_custom_model_can_be_associated_with_entity(self, test_domain):
        test_domain.register(Provider)
        test_domain.register_model(ProviderCustomModel, entity_cls=Provider)

        model_cls = test_domain.repository_for(Provider)._model
        assert model_cls.__name__ == "ProviderCustomModel"

    def test_that_explicit_schema_name_takes_precedence_over_generated(
        self, test_domain
    ):
        test_domain.register(Provider)
        test_domain.register_model(ProviderCustomModel, entity_cls=Provider)

        # FIXME Should schema name be equated to the overridden name in the model?
        assert Provider.meta_.schema_name == "provider"
        assert ProviderCustomModel.meta_.schema == "providers"

        model = test_domain.repository_for(Provider)._model
        assert model._index._name == "providers"

    def test_that_custom_model_is_persisted_via_dao(self, test_domain):
        test_domain.register(Provider)
        test_domain.register_model(ProviderCustomModel, entity_cls=Provider)

        provider_dao = test_domain.repository_for(Provider)._dao
        provider = provider_dao.create(name="John", about="Me, Myself, and Jane")
        assert provider is not None

    def test_that_custom_model_is_retrievable_via_dao(self, test_domain):
        test_domain.register(Provider)
        test_domain.register_model(ProviderCustomModel, entity_cls=Provider)

        provider_dao = test_domain.repository_for(Provider)._dao
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
        provider = test_domain.providers["default"]
        conn = provider.get_connection()

        for _, aggregate_record in test_domain.registry.aggregates.items():
            index = Index(aggregate_record.cls.meta_.schema_name, using=conn)
            if not index.exists():
                index.create()
        # Ensure that index is created for `Receiver` - END

        model_cls = test_domain.repository_for(Receiver)._model
        assert model_cls.__name__ == "ReceiverInlineModel"
        assert model_cls.name._params["fields"] == {"raw": Keyword()}

    def test_persistence_via_model_registered_with_domain_annotation(self, test_domain):
        from elasticsearch_dsl import Keyword, Text

        test_domain.register(Receiver)

        @test_domain.model(entity_cls=Receiver)
        class ReceiverInlineModel:
            id = Keyword()
            name = Text(fields={"raw": Keyword()})

        # Create the index
        model_cls = test_domain.repository_for(Receiver)._model
        conn = test_domain.providers["default"].get_connection()
        if model_cls._index.exists(using=conn):
            conn.indices.delete(model_cls._index._name)
        model_cls.init(using=conn)

        receiver_dao = test_domain.repository_for(Receiver)._dao
        receiver = receiver_dao.create(name="John")

        receiver = receiver_dao.get(receiver.id)
        assert receiver is not None
        assert receiver.name == "John"

        conn.indices.delete(model_cls._index._name)
