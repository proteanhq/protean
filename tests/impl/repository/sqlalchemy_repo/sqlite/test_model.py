# Protean
from protean.impl.repository.sqlalchemy_repo import SqlalchemyModel

# Local/Relative Imports
from .elements import ComplexUser, Email, Person


class TestModel:
    def test_that_model_class_is_created_automatically(self, test_domain):
        model_cls = test_domain.get_provider('default').get_model(Person)
        assert issubclass(model_cls, SqlalchemyModel)
        assert model_cls.__name__ == 'PersonModel'

    def test_conversation_from_entity_to_model(self, test_domain):
        model_cls = test_domain.get_provider('default').get_model(Person)
        person = Person(first_name='John', last_name='Doe')
        person_model_obj = model_cls.from_entity(person)

        assert person_model_obj is not None
        assert isinstance(person_model_obj, SqlalchemyModel)
        assert person_model_obj.age == 21
        assert person_model_obj.first_name == 'John'
        assert person_model_obj.last_name == 'Doe'

    def test_conversation_from_model_to_entity(self, test_domain):
        model_cls = test_domain.get_provider('default').get_model(Person)
        person = Person(first_name='John', last_name='Doe')
        person_model_obj = model_cls.from_entity(person)

        person_copy = model_cls.to_entity(person_model_obj)
        assert person_copy is not None


class TestModelWithVO:
    def test_that_model_class_is_created_automatically(self, test_domain):
        model_cls = test_domain.get_provider('default').get_model(ComplexUser)
        assert issubclass(model_cls, SqlalchemyModel)
        assert model_cls.__name__ == 'ComplexUserModel'

    def test_conversation_from_entity_to_model(self, test_domain):
        model_cls = test_domain.get_provider('default').get_model(ComplexUser)

        user1 = ComplexUser(email_address='john.doe@gmail.com', password='d4e5r6')
        user2 = ComplexUser(email=Email(address='john.doe@gmail.com'), password='d4e5r6')

        user1_model_obj = model_cls.from_entity(user1)
        user2_model_obj = model_cls.from_entity(user2)

        assert user1_model_obj is not None
        assert isinstance(user1_model_obj, SqlalchemyModel)
        assert user1_model_obj.email_address == 'john.doe@gmail.com'
        assert user1_model_obj.password == 'd4e5r6'

        assert user2_model_obj is not None
        assert isinstance(user2_model_obj, SqlalchemyModel)
        assert user2_model_obj.email_address == 'john.doe@gmail.com'
        assert user2_model_obj.password == 'd4e5r6'

        # Model's content should reflect only the attributes, not declared_fields
        assert hasattr(user1_model_obj, 'email') is False
        assert hasattr(user2_model_obj, 'email') is False

    def test_conversation_from_model_to_entity(self, test_domain):
        model_cls = test_domain.get_provider('default').get_model(ComplexUser)
        user1 = ComplexUser(email_address='john.doe@gmail.com', password='d4e5r6')
        user1_model_obj = model_cls.from_entity(user1)

        user_copy = model_cls.to_entity(user1_model_obj)
        assert user_copy is not None
