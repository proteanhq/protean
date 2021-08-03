import pytest

from protean.exceptions import NotSupportedError

from .elements import AbstractRole, ConcreteRole


class TestAggregateAbstraction:
    def test_that_abstract_entities_cannot_be_registered_or_initialized(
        self, test_domain
    ):
        with pytest.raises(NotSupportedError) as exc1:
            test_domain.register(AbstractRole)
        assert exc1.value.args[0] == (
            "AbstractRole class has been marked abstract" " and cannot be instantiated"
        )

        with pytest.raises(NotSupportedError) as exc2:
            AbstractRole(name="Titan")
        assert exc2.value.args[0] == (
            "AbstractRole class has been marked abstract" " and cannot be instantiated"
        )

    def test_that_concrete_entities_can_be_created_from_abstract_entities_through_inheritance(
        self, test_domain
    ):
        test_domain.register(ConcreteRole)
        concrete_role = ConcreteRole(name="Titan")
        assert concrete_role is not None
        assert concrete_role.name == "Titan"

    def test_that_abstract_entities_can_be_created_with_annotations(self, test_domain):
        from protean.core.aggregate import BaseAggregate
        from protean.core.field.basic import String

        class CustomBaseClass(BaseAggregate):
            foo = String(max_length=25)

            class Meta:
                abstract = True

        @test_domain.aggregate
        class ConcreateSubclass(CustomBaseClass):
            bar = String(max_length=25)

        assert all(
            key in ConcreateSubclass.meta_.declared_fields for key in ["foo", "bar"]
        )

        concrete = ConcreateSubclass(foo="Saturn", bar="Titan")
        assert concrete is not None
        assert concrete.foo == "Saturn"
        assert concrete.bar == "Titan"
