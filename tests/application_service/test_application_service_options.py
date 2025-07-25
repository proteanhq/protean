import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.application_service import BaseApplicationService
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import String


class User(BaseAggregate):
    email = String()
    name = String()


def test_that_base_command_handler_cannot_be_instantianted():
    with pytest.raises(NotSupportedError):
        BaseApplicationService()


def test_part_of_specified_during_registration(test_domain):
    class UserApplicationService(BaseApplicationService):
        pass

    test_domain.register(UserApplicationService, part_of=User)
    assert UserApplicationService.meta_.part_of == User


def test_part_of_defined_via_annotation(
    test_domain,
):
    @test_domain.application_service(part_of=User)
    class UserApplicationService:
        pass

    assert UserApplicationService.meta_.part_of == User


def test_part_of_is_mandatory(test_domain):
    class UserApplicationService(BaseApplicationService):
        pass

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(UserApplicationService)

    assert (
        exc.value.args[0]
        == "Application Service `UserApplicationService` needs to be associated with an aggregate"
    )
