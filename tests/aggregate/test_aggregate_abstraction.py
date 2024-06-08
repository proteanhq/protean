import pytest

from protean.exceptions import NotSupportedError
from protean.fields import String
from protean.reflection import declared_fields

from .elements import AbstractRole, ConcreteRole


class TestAggregateAbstraction:
    def test_that_abstract_entities_cannot_be_initialized(self, test_domain):
        test_domain.register(AbstractRole, abstract=True)

        with pytest.raises(NotSupportedError) as exc2:
            AbstractRole(foo="Titan")
        assert exc2.value.args[0] == (
            "AbstractRole class has been marked abstract" " and cannot be instantiated"
        )

    def test_that_concrete_entities_can_be_created_from_abstract_entities_through_inheritance(
        self, test_domain
    ):
        test_domain.register(ConcreteRole)
        concrete_role = ConcreteRole(foo="Titan")
        assert concrete_role is not None
        assert concrete_role.foo == "Titan"

    def test_that_abstract_entities_can_be_created_with_annotations(self, test_domain):
        @test_domain.aggregate(abstract=True)
        class CustomBaseClass:
            foo = String(max_length=25)

        @test_domain.aggregate
        class ConcreateSubclass(CustomBaseClass):
            bar = String(max_length=25)

        assert all(key in declared_fields(ConcreateSubclass) for key in ["foo", "bar"])

        concrete = ConcreateSubclass(foo="Saturn", bar="Titan")
        assert concrete is not None
        assert concrete.foo == "Saturn"
        assert concrete.bar == "Titan"
