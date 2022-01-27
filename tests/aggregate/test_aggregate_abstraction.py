import pytest

from protean.exceptions import NotSupportedError
from protean.reflection import declared_fields

from .elements import AbstractRole, ConcreteRole


class TestAggregateAbstraction:
    def test_that_abstract_entities_cannot_be_initialized(self):
        with pytest.raises(NotSupportedError) as exc2:
            AbstractRole(name="Titan")
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
        from protean import BaseAggregate
        from protean.fields import String

        class CustomBaseClass(BaseAggregate):
            foo = String(max_length=25)

            class Meta:
                abstract = True

        @test_domain.aggregate
        class ConcreateSubclass(CustomBaseClass):
            bar = String(max_length=25)

        assert all(key in declared_fields(ConcreateSubclass) for key in ["foo", "bar"])

        concrete = ConcreateSubclass(foo="Saturn", bar="Titan")
        assert concrete is not None
        assert concrete.foo == "Saturn"
        assert concrete.bar == "Titan"
