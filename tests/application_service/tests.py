import pytest

from protean.core.application_service import BaseApplicationService
from protean.utils import fully_qualified_name

from .elements import DummyApplicationService


class TestApplicationServiceInitialization:
    def test_that_base_application_service_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseApplicationService()

    def test_that_application_service_can_be_instantiated(self):
        service = DummyApplicationService()
        assert service is not None


class TestApplicationServiceRegistration:
    def test_that_application_service_can_be_registered_with_domain(self, test_domain):
        test_domain.register(DummyApplicationService)

        assert (
            fully_qualified_name(DummyApplicationService)
            in test_domain.registry.application_services
        )

    def test_that_application_service_can_be_registered_via_annotations(
        self, test_domain
    ):
        @test_domain.application_service
        class AnnotatedApplicationService:
            def special_method(self):
                pass

        assert (
            fully_qualified_name(AnnotatedApplicationService)
            in test_domain.registry.application_services
        )
