import mock
import pytest


from protean import BaseAggregate, BaseDomainService
from protean.core import domain_service
from protean.exceptions import IncorrectUsageError
from protean.utils import fully_qualified_name


class Aggregate1(BaseAggregate):
    pass


class Aggregate2(BaseAggregate):
    pass


class perform_something(BaseDomainService):
    class Meta:
        part_of = [Aggregate1, Aggregate2]

    def __call__(self):
        print("Performing complex process...")


def test_that_base_domain_service_class_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseDomainService()


def test_that_domain_service_can_be_instantiated():
    service = perform_something(Aggregate1(), Aggregate2())
    assert service is not None


def test_that_domain_service_needs_to_be_associated_with_at_least_2_aggregates(
    test_domain,
):
    with pytest.raises(IncorrectUsageError):

        class bad_domain_service(BaseDomainService):
            class Meta:
                part_of = [Aggregate1]

        test_domain.register(bad_domain_service)


def test_that_domain_service_is_a_callable_class():
    assert callable(perform_something(Aggregate1(), Aggregate2()))


def test_that_domain_service_can_be_registered_with_domain(test_domain):
    test_domain.register(perform_something)

    assert (
        fully_qualified_name(perform_something) in test_domain.registry.domain_services
    )


def test_that_domain_service_can_be_registered_via_annotations(test_domain):
    @test_domain.domain_service(part_of=[Aggregate1, Aggregate2])
    class AnnotatedDomainService:
        def special_method(self):
            pass

    assert (
        fully_qualified_name(AnnotatedDomainService)
        in test_domain.registry.domain_services
    )


def test_that_domain_service_is_associated_with_aggregates(test_domain):
    @test_domain.aggregate
    class Aggregate3:
        pass

    @test_domain.aggregate
    class Aggregate4:
        pass

    @test_domain.domain_service(part_of=[Aggregate3, Aggregate4])
    class do_something:
        pass

    assert fully_qualified_name(do_something) in test_domain.registry.domain_services
    assert (
        Aggregate3
        in test_domain.registry.domain_services[
            fully_qualified_name(do_something)
        ].cls.meta_.part_of
    )
    assert (
        Aggregate4
        in test_domain.registry.domain_services[
            fully_qualified_name(do_something)
        ].cls.meta_.part_of
    )


def test_wrap_call_method_with_invariants(test_domain):
    # Mock the `wrap_call_method_with_invariants` method
    #   Ensure it returns a domain service element
    mock_wrap = mock.Mock(return_value=perform_something)
    domain_service.wrap_call_method_with_invariants = mock_wrap

    test_domain.register(perform_something)

    mock_wrap.assert_called_once()
