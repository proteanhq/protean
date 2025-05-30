import pytest

from protean.core.projector import BaseProjector, on
from protean.exceptions import IncorrectUsageError, NotSupportedError

from .elements import LoggedIn, LoggedOut, Token, TokenProjector, User


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)
    test_domain.register(LoggedIn, part_of=User)
    test_domain.register(LoggedOut, part_of=User)
    test_domain.register(Token)
    test_domain.register(TokenProjector, projector_for=Token, aggregates=[User])


def test_that_base_command_handler_cannot_be_instantianted():
    with pytest.raises(NotSupportedError):
        BaseProjector()


def test_projectors_can_only_be_associated_with_projections(test_domain):
    class UserProjector(BaseProjector):
        @on(LoggedIn)
        def project_user(self, event: LoggedIn):
            pass

    test_domain.register(UserProjector, projector_for=User, aggregates=[User])

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.init(traverse=False)
    assert exc.value.args[0] == (
        "`User` is not a Projection, or is not registered in domain Test"
    )
