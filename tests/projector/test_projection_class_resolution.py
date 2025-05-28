import pytest

from protean.utils import fqn

from .elements import LoggedIn, LoggedOut, Token, TokenProjector, User


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)
    test_domain.register(LoggedIn, part_of=User)
    test_domain.register(LoggedOut, part_of=User)
    test_domain.register(Token)
    test_domain.register(TokenProjector, projector_for="Token", aggregates=[User])

    test_domain.init(traverse=False)


def test_projection_class_resolution(test_domain):
    assert (
        test_domain.registry.projectors[fqn(TokenProjector)].cls.meta_.projector_for
        == Token
    )
