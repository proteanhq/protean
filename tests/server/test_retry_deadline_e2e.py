"""End-to-end: a deadline-stopped retry behaves like an exhausted retry.

The transient-retry loop stops (and re-raises) when the next attempt would
start past the command deadline. This drives a deadline-bearing command
through the real ``Engine`` to confirm the re-raise routes through the normal
error path:

- the handler runs exactly once (no retry sleeps past the deadline),
- ``handle_error`` is invoked (it is not a silent skip), and
- ``handle_message`` returns ``False`` — the exact gate that prevents a false
  idempotent ``record_success`` (see ``event_store_subscription`` line that
  records only ``if is_successful``), so the command is eligible for redelivery
  rather than being marked done.
"""

import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils.eventing import Message
from protean.utils.mixins import handle

attempts = 0
errors_handled = 0


class Order(BaseAggregate):
    id = Identifier(identifier=True)
    note = String()


class Submit(BaseCommand):
    order_id = Identifier()


class FlakyHandler(BaseCommandHandler):
    @handle(Submit)
    def submit(self, command: Submit) -> None:
        global attempts
        attempts += 1
        raise ConnectionError("transient down")

    @classmethod
    def handle_error(cls, exc, message) -> None:
        global errors_handled
        errors_handled += 1


@pytest.fixture(autouse=True)
def elements(test_domain):
    test_domain.register(Order, is_event_sourced=True)
    test_domain.register(Submit, part_of=Order)
    # Retry enabled with an enormous backoff so any retry would breach a
    # near-future deadline.
    test_domain.register(FlakyHandler, part_of=Order, retries=3, backoff="fixed")
    test_domain.init(traverse=False)
    test_domain.config["server"]["transient_retry"]["base_delay_seconds"] = 3600


@pytest.fixture(autouse=True)
def reset():
    global attempts, errors_handled
    attempts = 0
    errors_handled = 0
    yield


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    """Fail fast instead of hanging if a backoff sleep is ever attempted.

    The deadline guard must stop the retry loop *before* any backoff sleep. With
    ``base_delay_seconds = 3600`` a real sleep would hang the suite for an hour,
    so make the retry's ``time.sleep`` raise: a guard regression then fails
    immediately with a clear message instead of timing out the run.

    The patch is scoped to the ``time`` symbol *inside* ``protean.utils.mixins``
    (via a proxy that overrides only ``sleep`` and delegates everything else to
    the real module), so an unrelated ``time.sleep`` elsewhere in the engine is
    unaffected and cannot trip this assertion.
    """

    def _fail(seconds: float) -> None:
        raise AssertionError(
            f"retry attempted a {seconds}s backoff sleep; the deadline guard "
            "should have stopped the loop before sleeping"
        )

    class _TimeProxy:
        sleep = staticmethod(_fail)

        def __getattr__(self, name):
            return getattr(time, name)

    monkeypatch.setattr("protean.utils.mixins.time", _TimeProxy())


def _message_with_deadline(test_domain, deadline):
    command = Submit(order_id=str(uuid4()))
    enriched = test_domain._command_processor.enrich(
        command, asynchronous=True, deadline=deadline
    )
    return Message.from_domain_object(enriched)


@pytest.mark.asyncio
async def test_deadline_stopped_retry_routes_through_error_path(test_domain):
    # Deadline is a couple of seconds out, so the first attempt runs; the
    # 3600s backoff would push any retry well past it, so the loop stops.
    near = datetime.now(timezone.utc) + timedelta(seconds=2)
    message = _message_with_deadline(test_domain, near)

    engine = Engine(domain=test_domain, test_mode=True)
    result = await engine.handle_message(FlakyHandler, message)

    global attempts, errors_handled
    # Ran exactly once — no retry slept past the deadline.
    assert attempts == 1
    # The failure routed through the normal error path, not a silent skip...
    assert errors_handled == 1
    # ...and `handle_message` reported failure, so the command is never
    # recorded as an idempotent success (eligible for redelivery).
    assert result is False


@pytest.mark.asyncio
async def test_already_expired_command_is_skipped_before_any_attempt(test_domain):
    # Negative control: an already-elapsed deadline is skipped by the engine
    # before dispatch, so the handler never runs and the error path is bypassed.
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    message = _message_with_deadline(test_domain, past)

    engine = Engine(domain=test_domain, test_mode=True)
    result = await engine.handle_message(FlakyHandler, message)

    global attempts, errors_handled
    assert attempts == 0  # handler never ran
    assert errors_handled == 0  # not routed through the error path
    assert result is True  # acknowledged (position advances), not retried
