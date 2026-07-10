"""Tests that the async engine rejects commands whose deadline elapsed in queue."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils.eventing import Message
from protean.utils.mixins import handle

counter = 0
error_handled = 0


class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()


class Register(BaseCommand):
    user_id: Identifier()
    email: String()


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register) -> None:
        global counter
        counter += 1

    @classmethod
    def handle_error(cls, exc, message) -> None:
        # Expired commands must NOT reach the error handler — they are
        # intentional skips, not failures.
        global error_handled
        error_handled += 1


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def reset_counter():
    global counter, error_handled
    counter = 0
    error_handled = 0
    yield


def _message_with_deadline(test_domain, deadline):
    command = Register(user_id=str(uuid4()), email="john.doe@example.com")
    enriched = test_domain._command_processor.enrich(
        command, asynchronous=True, deadline=deadline
    )
    return Message.from_domain_object(enriched)


@pytest.mark.asyncio
async def test_expired_command_is_skipped_not_failed(test_domain):
    past = datetime.now(UTC) - timedelta(seconds=1)
    message = _message_with_deadline(test_domain, past)

    engine = Engine(domain=test_domain, test_mode=True)
    result = await engine.handle_message(UserCommandHandler, message)

    global counter, error_handled
    # Acknowledged (position advances, no retry) but never executed, and the
    # error/recovery path is bypassed.
    assert result is True
    assert counter == 0  # handler never ran
    assert error_handled == 0  # not routed through handle_error


@pytest.mark.asyncio
async def test_non_expired_command_is_handled(test_domain):
    future = datetime.now(UTC) + timedelta(minutes=5)
    message = _message_with_deadline(test_domain, future)

    engine = Engine(domain=test_domain, test_mode=True)
    result = await engine.handle_message(UserCommandHandler, message)

    global counter
    assert result is True
    assert counter == 1
