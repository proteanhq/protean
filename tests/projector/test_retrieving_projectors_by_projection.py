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
    test_domain.register(Registered, part_of=User)
    test_domain.register(LoggedIn, part_of=User)
    test_domain.register(LoggedOut, part_of=User)
    test_domain.register(Token)
    test_domain.register(FullUser)
    test_domain.register(NewUserReport)
    test_domain.register(TokenProjector, projector_for=Token, aggregates=[User])
    test_domain.register(FullUserProjector, projector_for=FullUser, aggregates=[User])
    test_domain.register(
        NewUserProjector, projector_for=NewUserReport, aggregates=[User]
    )
    test_domain.init(traverse=False)


def test_retrieving_projector_by_projection(test_domain):
    assert test_domain.projectors_for(Token) == {TokenProjector}
    assert test_domain.projectors_for(FullUser) == {FullUserProjector}
    assert test_domain.projectors_for(NewUserReport) == {NewUserProjector}
