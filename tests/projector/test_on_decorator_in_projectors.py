import pytest

from .elements import LoggedIn, LoggedOut, Token, TokenProjector, User


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(LoggedIn, part_of=User)
    test_domain.register(LoggedOut, part_of=User)
    test_domain.register(Token)
    test_domain.register(TokenProjector, projector_for=Token, aggregates=[User])
    test_domain.init(traverse=False)


def test_that_a_handler_is_recorded_against_projector(test_domain):
    assert LoggedIn.__type__ in TokenProjector._handlers
    assert LoggedOut.__type__ in TokenProjector._handlers


def test_that_multiple_handlers_can_be_recorded_against_the_same_event(test_domain):
    """This test is to ensure that multiple handlers can be recorded against diffrent events
    and against the same event"""
    test_domain.register(User)
    test_domain.register(LoggedIn, part_of=User)
    test_domain.register(LoggedOut, part_of=User)
    test_domain.register(Token)
    test_domain.register(TokenProjector, projector_for=Token, aggregates=[User])
    test_domain.init(traverse=False)

    assert len(TokenProjector._handlers) == 2
    assert all(
        handle_name in TokenProjector._handlers
        for handle_name in [
            LoggedIn.__type__,
            LoggedOut.__type__,
        ]
    )

    assert len(TokenProjector._handlers[LoggedIn.__type__]) == 2
    assert len(TokenProjector._handlers[LoggedOut.__type__]) == 1

    handlers_for_logged_in = TokenProjector._handlers[LoggedIn.__type__]
    assert all(
        handler_method in handlers_for_logged_in
        for handler_method in [
            TokenProjector.on_logged_in,
            TokenProjector.on_logged_in_2,
        ]
    )
    assert (
        next(iter(TokenProjector._handlers[LoggedOut.__type__]))
        == TokenProjector.on_logged_out
    )
