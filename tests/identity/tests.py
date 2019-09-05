from .elements import Person


class TestIdentityType:

    def test_string_identity(self, test_domain_with_string_identity):
        person = Person(first_name='John', last_name='Doe')
        assert person.id is not None
        assert isinstance(person.id, str)

    def test_int_identity(self, test_domain_with_int_identity):
        person = Person(first_name='John', last_name='Doe')
        assert person.id is not None
        assert isinstance(person.id, int)
