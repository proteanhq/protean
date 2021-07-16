import pytest

from protean.core.domain_service import BaseDomainService
from protean.utils import fully_qualified_name

from .elements import DummyDomainService


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
        @test_domain.domain_service
        class AnnotatedDomainService:
            def special_method(self):
                pass

        assert (
            fully_qualified_name(AnnotatedDomainService)
            in test_domain.registry.domain_services
        )
