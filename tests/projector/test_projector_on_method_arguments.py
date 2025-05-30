import pytest

from protean.core.projector import BaseProjector, on
from protean.exceptions import IncorrectUsageError

from .elements import LoggedIn, LoggedOut, Token, TokenProjector, User


class DummyProjector(BaseProjector):
    @on(LoggedIn)
    def on_logged_in(self, event: LoggedIn):
        pass

    @on(Token)
    def on_token(self, event: Token):
        pass


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)
    test_domain.register(LoggedIn, part_of=User)
    test_domain.register(LoggedOut, part_of=User)
    test_domain.register(Token)
    test_domain.register(TokenProjector, projector_for="Token", aggregates=[User])


def test_on_method_arguments_can_only_be_event_classes(test_domain):
    with pytest.raises(IncorrectUsageError) as excinfo:
        test_domain.register(DummyProjector, projector_for="Token", aggregates=[User])
        test_domain.init(traverse=False)
    assert "is not associated with an event" in str(excinfo.value)
