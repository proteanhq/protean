import pytest

from protean import BaseDomainService
from protean.utils import fully_qualified_name


def Aggregate1(BaseAggregate):
    pass


def Aggregate2(BaseAggregate):
    pass


class DummyDomainService(BaseDomainService):
    class Meta:
        part_of = [Aggregate1, Aggregate2]

    def do_complex_process(self):
        print("Performing complex process...")


class TestDomainServiceInitialization:
    def test_that_base_domain_service_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseDomainService()

    def test_that_domain_service_can_be_instantiated(self):
        service = DummyDomainService()
        assert service is not None


class TestDomainServiceRegistration:
    def test_that_domain_service_can_be_registered_with_domain(self, test_domain):
        test_domain.register(DummyDomainService)

        assert (
            fully_qualified_name(DummyDomainService)
            in test_domain.registry.domain_services
        )

    def test_that_domain_service_can_be_registered_via_annotations(self, test_domain):
        @test_domain.domain_service(part_of=[Aggregate1, Aggregate2])
        class AnnotatedDomainService:
            def special_method(self):
                pass

        assert (
            fully_qualified_name(AnnotatedDomainService)
            in test_domain.registry.domain_services
        )

    def test_that_domain_service_is_associated_with_aggregates(self, test_domain):
        @test_domain.aggregate
        class Aggregate3:
            pass

        @test_domain.aggregate
        class Aggregate4:
            pass

        @test_domain.domain_service(part_of=[Aggregate3, Aggregate4])
        class AnnotatedDomainService:
            def special_method(self):
                pass

        assert (
            fully_qualified_name(AnnotatedDomainService)
            in test_domain.registry.domain_services
        )
        assert (
            Aggregate3
            in test_domain.registry.domain_services[
                fully_qualified_name(AnnotatedDomainService)
            ].cls.meta_.part_of
        )
        assert (
            Aggregate4
            in test_domain.registry.domain_services[
                fully_qualified_name(AnnotatedDomainService)
            ].cls.meta_.part_of
        )
