"""End-to-end regression test (ADR-0031).

Two event handler *classes* registered for the same event are independent
reactions to one fact. Under async each has its own subscription, so one failing
never touches the other. Under ``event_processing = "sync"`` the drain used to
stop at the first class that raised, so a sibling class registered behind it
never ran. These tests drive the real ``repository.add`` -> Unit of Work commit
-> synchronous dispatch path and assert every class runs, and that the failure
still surfaces to the caller in the shape the commit produces.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.exceptions import TransactionError
from protean.fields import Identifier, String
from protean.utils.mixins import handle

ran: list[str] = []


class Registered(BaseEvent):
    user_id = Identifier()


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    name = String()

    @classmethod
    def register(cls, user_id: str, name: str) -> "User":
        user = cls(user_id=user_id, name=name)
        user.raise_(Registered(user_id=user_id))
        return user


class FirstReaction(BaseEventHandler):
    @handle(Registered)
    def react(self, event: Registered) -> None:
        ran.append("first")
        raise RuntimeError("first reaction failed")


class SecondReaction(BaseEventHandler):
    @handle(Registered)
    def react(self, event: Registered) -> None:
        ran.append("second")


class SecondReactionFails(BaseEventHandler):
    @handle(Registered)
    def react(self, event: Registered) -> None:
        ran.append("second")
        raise ValueError("second reaction failed")


def _register(test_domain, *reactions):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    for reaction in reactions:
        test_domain.register(reaction, part_of=User)
    test_domain.init(traverse=False)


def test_a_failing_class_does_not_skip_its_sibling_and_the_failure_surfaces(
    test_domain,
):
    """One class fails, one succeeds. Both run, and the commit surfaces the lone
    failure as a ``TransactionError`` whose ``__cause__`` is the original
    exception. (The deterministic revert guard is the FIFO unit test; ``handlers_for``
    is a set, so order here is not fixed — both running is what the fix guarantees.)"""
    _register(test_domain, FirstReaction, SecondReaction)

    ran.clear()
    with test_domain.domain_context():
        user = User.register(str(uuid4()), "John Doe")
        with pytest.raises(TransactionError) as exc_info:
            test_domain.repository_for(User).add(user)

    assert sorted(ran) == ["first", "second"]
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_two_failing_classes_both_run_and_surface_as_a_grouped_cause(test_domain):
    """Two classes fail for one event. Both run, and the commit wraps the
    ``ExceptionGroup`` as the ``TransactionError``'s ``__cause__`` — the shape the
    migration guide tells upgraders to reach through ``__cause__``."""
    _register(test_domain, FirstReaction, SecondReactionFails)

    ran.clear()
    with test_domain.domain_context():
        user = User.register(str(uuid4()), "John Doe")
        with pytest.raises(TransactionError) as exc_info:
            test_domain.repository_for(User).add(user)

    assert sorted(ran) == ["first", "second"]
    cause = exc_info.value.__cause__
    assert isinstance(cause, ExceptionGroup)
    assert sorted(type(e).__name__ for e in cause.exceptions) == [
        "RuntimeError",
        "ValueError",
    ]
