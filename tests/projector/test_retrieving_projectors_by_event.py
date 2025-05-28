import pytest

from .elements import (
    FullUser,
    FullUserProjector,
    LoggedIn,
    LoggedOut,
    NewUserProjector,
    NewUserReport,
    Registered,
    Token,
    TokenProjector,
    User,
)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(LoggedIn, part_of=User)
    test_domain.register(LoggedOut, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Token)
    test_domain.register(FullUser)
    test_domain.register(NewUserReport)
    test_domain.register(TokenProjector, projector_for=Token, aggregates=[User])
    test_domain.register(FullUserProjector, projector_for=FullUser, aggregates=[User])
    test_domain.register(
        NewUserProjector, projector_for=NewUserReport, aggregates=[User]
    )

    test_domain.init(traverse=False)


def test_retrieving_handler_by_event(test_domain):
    assert test_domain.handlers_for(LoggedIn()) == {
        TokenProjector,
        FullUserProjector,
    }
    assert test_domain.handlers_for(LoggedOut()) == {
        TokenProjector,
        FullUserProjector,
    }
    assert test_domain.handlers_for(Registered()) == {
        FullUserProjector,
        NewUserProjector,
    }
