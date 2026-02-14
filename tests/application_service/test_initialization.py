import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.application_service import BaseApplicationService
from protean.exceptions import NotSupportedError
from protean.utils import fully_qualified_name


class DummyAggregate(BaseAggregate):
    pass


class DummyApplicationService(BaseApplicationService):
    def do_application_process(self):
        print("Performing application process...")


class TestApplicationServiceInitialization:
    def test_that_base_application_service_class_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError):
            BaseApplicationService()

    def test_that_application_service_can_be_instantiated(self):
        service = DummyApplicationService()
        assert service is not None


class TestApplicationServiceRegistration:
    def test_that_application_service_can_be_registered_with_domain(self, test_domain):
        test_domain.register(DummyApplicationService, part_of=DummyAggregate)

        assert (
            fully_qualified_name(DummyApplicationService)
            in test_domain.registry.application_services
        )

    def test_that_application_service_can_be_registered_via_annotations(
        self, test_domain
    ):
        @test_domain.application_service(part_of=DummyAggregate)
        class AnnotatedApplicationService:
            def special_method(self):
                pass

        assert (
            fully_qualified_name(AnnotatedApplicationService)
            in test_domain.registry.application_services
        )

    def test_that_application_service_part_of_is_resolve_on_domain_init(
        self, test_domain
    ):
        test_domain.register(DummyAggregate)
        test_domain.register(DummyApplicationService, part_of="DummyAggregate")
        test_domain.init(traverse=False)

        assert DummyApplicationService.meta_.part_of == DummyAggregate
