"""``domain.process(command, asynchronous=True)`` in a domain with
``command_processing = "sync"``.

Outside any unit of work the command is handled inline. Inside one (a handler,
a ``@use_case`` method or a ``with UnitOfWork():`` block) it is stored with the
caller's writes, ``process`` returns ``None``, and the command is handled after
the caller commits, in its own unit of work with its own version retry. A
conflict there never re-runs the caller, so an outside call the caller made
before ``process`` happens once. Either way the command is stored as not
asynchronous, so the engine's command subscription skips it.
"""

import asyncio
import threading
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.application_service import BaseApplicationService, use_case
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain
from protean.exceptions import (
    CommandExpiredError,
    ExpectedVersionError,
    TransactionError,
)
from protean.fields import Identifier, Integer, String
from protean.server import Engine
from protean.server.engine import CommandDispatcher
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
)
from protean.utils import Processing
from protean.utils.globals import current_domain
from protean.utils.mixins import handle
from tests.shared import POSTGRES_URI


class DispatchStarted(BaseEvent):
    notification_id = Identifier(required=True)


class ResultRecorded(BaseEvent):
    notification_id = Identifier(required=True)
    status = String(required=True)


class Notification(BaseAggregate):
    status = String(max_length=20, default="PENDING")
    touched = Integer(default=0)

    @classmethod
    def start(cls) -> "Notification":
        notification = cls()
        notification.raise_(DispatchStarted(notification_id=notification.id))
        return notification

    def record(self, status: str) -> None:
        self.status = status
        self.raise_(ResultRecorded(notification_id=self.id, status=status))


class RecordResult(BaseCommand):
    notification_id = Identifier(identifier=True)
    status = String(required=True)


class Probe:
    """What the handlers did, reset per test."""

    channel: list[str] = []
    attempts: int = 0
    conflicts_left: int = 0
    fail_with: Exception | None = None
    recorded_events: list[str] = []

    @classmethod
    def reset(cls) -> None:
        cls.channel = []
        cls.attempts = 0
        cls.conflicts_left = 0
        cls.fail_with = None
        cls.recorded_events = []


def _write_concurrently(notification_id: str) -> None:
    """Save the notification from another thread, so the save that loaded it
    before this write fails its version check."""
    domain = current_domain._get_current_object()

    def bump() -> None:
        with domain.domain_context():
            with UnitOfWork():
                repo = domain.repository_for(Notification)
                notification = repo.get(notification_id)
                notification.touched += 1
                repo.add(notification)

    thread = threading.Thread(target=bump)
    thread.start()
    thread.join()


class RecordResultHandler(BaseCommandHandler):
    @handle(RecordResult)
    def record(self, command: RecordResult) -> str:
        Probe.attempts += 1
        if Probe.fail_with is not None:
            raise Probe.fail_with
        repo = current_domain.repository_for(Notification)
        notification = repo.get(command.notification_id)
        if Probe.conflicts_left:
            Probe.conflicts_left -= 1
            _write_concurrently(command.notification_id)
        notification.record(command.status)
        repo.add(notification)
        return f"recorded-{command.status}"


class Dispatcher(BaseEventHandler):
    """Calls the channel, then records its result. It reaches no repository
    before the call."""

    @handle(DispatchStarted)
    def send(self, event: DispatchStarted) -> None:
        Probe.channel.append(event.notification_id)
        current_domain.process(
            RecordResult(notification_id=event.notification_id, status="SENT"),
            asynchronous=True,
        )


class RecordedListener(BaseEventHandler):
    @handle(ResultRecorded)
    def on_recorded(self, event: ResultRecorded) -> None:
        Probe.recorded_events.append(event.status)


class NotificationService(BaseApplicationService):
    @use_case
    def record_later(self, notification_id: str) -> object:
        result = current_domain.process(
            RecordResult(notification_id=notification_id, status="SENT"),
            asynchronous=True,
        )
        # Still inside the use case's unit of work: nothing has run yet
        assert Probe.attempts == 0
        return result


def _register(domain: Domain) -> None:
    domain.register(Notification)
    domain.register(DispatchStarted, part_of=Notification)
    domain.register(ResultRecorded, part_of=Notification)
    domain.register(RecordResult, part_of=Notification)
    domain.register(RecordResultHandler, part_of=Notification)
    domain.register(Dispatcher, part_of=Notification)
    domain.register(RecordedListener, part_of=Notification)
    domain.register(NotificationService, part_of=Notification)
    domain.init(traverse=False)


@pytest.fixture(autouse=True)
def register_elements(request, test_domain):
    Probe.reset()
    if "no_test_domain" not in request.keywords:
        _register(test_domain)
    yield
    Probe.reset()


@pytest.fixture(autouse=True)
def no_sleep():
    with patch("protean.utils.mixins.time.sleep"):
        yield


def _create_notification(domain: Domain) -> str:
    """Save a notification without raising ``DispatchStarted``."""
    with UnitOfWork():
        notification = Notification()
        domain.repository_for(Notification).add(notification)
    return notification.id


def _status(domain: Domain, notification_id: str) -> str:
    return domain.repository_for(Notification).get(notification_id).status


def _stored_commands(domain: Domain) -> list:
    return domain.event_store.store.read(
        f"{Notification.meta_.stream_category}:command"
    )


def _stored_dispatch_started(domain: Domain) -> tuple[str, object]:
    """Save a notification that raises ``DispatchStarted``. Return its id and
    the stored event, which the engine would hand to a handler with no unit of
    work open."""
    with UnitOfWork():
        notification = Notification.start()
        domain.repository_for(Notification).add(notification)
    event_message = domain.event_store.store.read_last_message(
        f"{Notification.meta_.stream_category}-{notification.id}"
    )
    return notification.id, event_message


def _start_dispatch(domain: Domain) -> str:
    """Save a notification that raises ``DispatchStarted`` and run the
    dispatcher on it, the way the configured event processing would."""
    notification_id, event_message = _stored_dispatch_started(domain)
    if domain.config["event_processing"] == Processing.ASYNC.value:
        Dispatcher._handle(event_message)
    return notification_id


def _skipped_by_command_subscription(domain: Domain) -> int:
    """Feed the stored commands to an engine command subscription and return
    how many it handled."""
    engine = Engine(domain=domain, test_mode=True)
    stream_category = f"{Notification.meta_.stream_category}:command"
    dispatcher = CommandDispatcher(
        stream_category,
        {RecordResult.__type__: RecordResultHandler},
        RecordResultHandler,
    )
    subscription = EventStoreSubscription(engine, stream_category, dispatcher)
    messages = _stored_commands(domain)
    assert messages
    return asyncio.run(subscription.process_batch(messages))


@pytest.fixture(params=[Processing.SYNC.value, Processing.ASYNC.value])
def event_processing(request, test_domain):
    test_domain.config["event_processing"] = request.param
    return request.param


class TestOutsideCallHappensOnce:
    def test_record_step_conflict_retries_only_the_record_step(
        self, test_domain, event_processing
    ):
        Probe.conflicts_left = 1

        notification_id = _start_dispatch(test_domain)

        assert Probe.channel == [notification_id]
        assert Probe.attempts == 2
        assert _status(test_domain, notification_id) == "SENT"

    def test_exhausted_record_step_reports_transaction_error(
        self, test_domain, event_processing
    ):
        max_retries = test_domain.config["server"]["version_retry"]["max_retries"]
        Probe.conflicts_left = max_retries + 1

        with pytest.raises(TransactionError) as exc_info:
            _start_dispatch(test_domain)

        assert len(Probe.channel) == 1
        assert Probe.attempts == max_retries + 1
        cause = exc_info.value.__cause__
        if event_processing == Processing.SYNC.value:
            # The sync drain reports the dispatcher's own TransactionError
            assert isinstance(cause, TransactionError)
            cause = cause.__cause__
        assert isinstance(cause, ExpectedVersionError)


class TestOutsideAnyUnitOfWork:
    def test_handled_inline_and_stored_as_not_asynchronous(self, test_domain):
        notification_id = _create_notification(test_domain)

        result = test_domain.process(
            RecordResult(notification_id=notification_id, status="SENT"),
            asynchronous=True,
        )

        assert result == "recorded-SENT"
        assert Probe.attempts == 1
        stored = _stored_commands(test_domain)
        assert [m.metadata.domain.asynchronous for m in stored] == [False]

    def test_command_subscription_skips_it(self, test_domain):
        notification_id = _create_notification(test_domain)
        test_domain.process(
            RecordResult(notification_id=notification_id, status="SENT"),
            asynchronous=True,
        )

        assert _skipped_by_command_subscription(test_domain) == 0
        assert Probe.attempts == 1


class TestInsideUnitOfWork:
    def test_without_asynchronous_joins_the_callers_unit_of_work(self, test_domain):
        notification_id = _create_notification(test_domain)

        uow = UnitOfWork()
        uow.start()
        result = test_domain.process(
            RecordResult(notification_id=notification_id, status="SENT")
        )
        # Handled before `process` returned, inside the caller's transaction
        assert result == "recorded-SENT"
        assert Probe.attempts == 1
        uow.rollback()

        assert _status(test_domain, notification_id) == "PENDING"

    def test_in_a_handler_returns_none_before_the_handler_runs(self, test_domain):
        seen: dict[str, object] = {}

        class Caller(BaseEventHandler):
            @handle(DispatchStarted)
            def send(self, event: DispatchStarted) -> None:
                seen["result"] = current_domain.process(
                    RecordResult(notification_id=event.notification_id, status="X"),
                    asynchronous=True,
                )
                seen["attempts"] = Probe.attempts

        test_domain.config["event_processing"] = Processing.ASYNC.value
        test_domain.register(Caller, part_of=Notification)
        test_domain.init(traverse=False)
        notification_id, event_message = _stored_dispatch_started(test_domain)

        Caller._handle(event_message)

        assert seen == {"result": None, "attempts": 0}
        # The command ran once the handler's unit of work committed
        assert Probe.attempts == 1
        assert _status(test_domain, notification_id) == "X"

    def test_in_a_use_case_runs_after_the_use_case_commits(self, test_domain):
        notification_id = _create_notification(test_domain)

        result = NotificationService().record_later(notification_id)

        assert result is None
        assert Probe.attempts == 1
        assert _status(test_domain, notification_id) == "SENT"

    def test_in_a_unit_of_work_block_runs_after_the_block_commits(self, test_domain):
        notification_id = _create_notification(test_domain)

        with UnitOfWork():
            result = test_domain.process(
                RecordResult(notification_id=notification_id, status="SENT"),
                asynchronous=True,
            )
            assert result is None
            assert Probe.attempts == 0

        assert Probe.attempts == 1
        assert _status(test_domain, notification_id) == "SENT"

    def test_nested_unit_of_work_runs_the_command_once(self, test_domain):
        notification_id = _create_notification(test_domain)

        with UnitOfWork():
            with UnitOfWork():
                test_domain.process(
                    RecordResult(notification_id=notification_id, status="SENT"),
                    asynchronous=True,
                )
            assert Probe.attempts == 0

        assert Probe.attempts == 1

    def test_rolled_back_caller_never_runs_the_command(self, test_domain):
        class FailingCaller(BaseEventHandler):
            @handle(DispatchStarted)
            def send(self, event: DispatchStarted) -> None:
                current_domain.process(
                    RecordResult(notification_id=event.notification_id, status="X"),
                    asynchronous=True,
                )
                raise RuntimeError("caller failed")

        test_domain.config["event_processing"] = Processing.ASYNC.value
        test_domain.register(FailingCaller, part_of=Notification)
        test_domain.init(traverse=False)

        notification_id, event_message = _stored_dispatch_started(test_domain)

        with pytest.raises(RuntimeError, match="caller failed"):
            FailingCaller._handle(event_message)

        assert Probe.attempts == 0
        assert _status(test_domain, notification_id) == "PENDING"

    def test_stored_as_not_asynchronous_and_skipped_by_the_subscription(
        self, test_domain
    ):
        notification_id = _create_notification(test_domain)

        with UnitOfWork():
            test_domain.process(
                RecordResult(notification_id=notification_id, status="SENT"),
                asynchronous=True,
            )

        stored = _stored_commands(test_domain)
        assert [m.metadata.domain.asynchronous for m in stored] == [False]
        assert _skipped_by_command_subscription(test_domain) == 0
        assert Probe.attempts == 1

    def test_events_of_a_deferred_command_are_dispatched(self, test_domain):
        notification_id = _create_notification(test_domain)

        with UnitOfWork():
            test_domain.process(
                RecordResult(notification_id=notification_id, status="SENT"),
                asynchronous=True,
            )

        assert Probe.recorded_events == ["SENT"]

    def test_every_deferred_command_runs_when_one_fails(self, test_domain):
        first = _create_notification(test_domain)
        second = _create_notification(test_domain)

        with pytest.raises(TransactionError) as exc_info:
            with UnitOfWork():
                test_domain.process(
                    RecordResult(notification_id=str(uuid4()), status="SENT"),
                    asynchronous=True,
                )
                test_domain.process(
                    RecordResult(notification_id=second, status="SENT"),
                    asynchronous=True,
                )

        assert Probe.attempts == 2
        assert _status(test_domain, second) == "SENT"
        assert _status(test_domain, first) == "PENDING"
        assert exc_info.value.__cause__.__class__.__name__ == "ObjectNotFoundError"

    def test_several_failures_are_reported_together(self, test_domain):
        Probe.fail_with = RuntimeError("record failed")

        with pytest.raises(TransactionError) as exc_info:
            with UnitOfWork():
                for _ in range(2):
                    test_domain.process(
                        RecordResult(notification_id=str(uuid4()), status="SENT"),
                        asynchronous=True,
                    )

        assert Probe.attempts == 2
        cause = exc_info.value.__cause__
        assert isinstance(cause, ExceptionGroup)
        assert [str(e) for e in cause.exceptions] == ["record failed"] * 2


class TestAsyncDomainIsUnchanged:
    def test_returns_the_position_and_defers_nothing(self, test_domain):
        test_domain.config["command_processing"] = Processing.ASYNC.value
        notification_id = _create_notification(test_domain)

        with UnitOfWork() as uow:
            result = test_domain.process(
                RecordResult(notification_id=notification_id, status="SENT"),
                asynchronous=True,
            )
            assert uow._deferred_commands == []

        assert isinstance(result, int)
        assert Probe.attempts == 0
        stored = _stored_commands(test_domain)
        assert [m.metadata.domain.asynchronous for m in stored] == [True]


class TestDeadline:
    def test_expired_at_call_time_raises_and_stores_nothing(self, test_domain):
        notification_id = _create_notification(test_domain)
        past = test_domain.clock.now() - timedelta(seconds=1)

        with pytest.raises(CommandExpiredError):
            with UnitOfWork():
                test_domain.process(
                    RecordResult(notification_id=notification_id, status="SENT"),
                    asynchronous=True,
                    deadline=past,
                )

        assert _stored_commands(test_domain) == []
        assert Probe.attempts == 0

    def test_expired_before_commit_raises_and_a_repeat_runs(
        self, test_domain, idempotency_store
    ):
        notification_id = _create_notification(test_domain)
        now = test_domain.clock.now()

        with patch.object(test_domain.clock, "now", return_value=now):
            with pytest.raises(TransactionError) as exc_info:
                with UnitOfWork():
                    test_domain.process(
                        RecordResult(notification_id=notification_id, status="SENT"),
                        asynchronous=True,
                        idempotency_key="k",
                        timeout=timedelta(seconds=5),
                    )
                    test_domain.clock.now.return_value = now + timedelta(seconds=10)

            assert isinstance(exc_info.value.__cause__, CommandExpiredError)
            assert Probe.attempts == 0
            assert idempotency_store.entries["k"]["status"] == "error"

            with UnitOfWork():
                test_domain.process(
                    RecordResult(notification_id=notification_id, status="SENT"),
                    asynchronous=True,
                    idempotency_key="k",
                    timeout=timedelta(seconds=5),
                )

        assert Probe.attempts == 1
        assert _status(test_domain, notification_id) == "SENT"


class _DictIdempotencyStore:
    """An idempotency store kept in a dict, with the Redis store's outcomes."""

    def __init__(self) -> None:
        self.entries: dict[str, dict] = {}

    @property
    def is_active(self) -> bool:
        return True

    def check(self, idempotency_key: str) -> dict | None:
        return self.entries.get(idempotency_key)

    def record_success(self, idempotency_key: str, result: object) -> None:
        self.entries[idempotency_key] = {"status": "success", "result": result}

    def record_error(self, idempotency_key: str, error: str) -> None:
        self.entries[idempotency_key] = {"status": "error", "error": error}


@pytest.fixture
def idempotency_store(test_domain, monkeypatch):
    store = _DictIdempotencyStore()
    monkeypatch.setattr(test_domain, "_idempotency_store", store)
    return store


@pytest.mark.usefixtures("idempotency_store")
class TestIdempotency:
    def _process(self, domain: Domain, notification_id: str) -> object:
        with UnitOfWork():
            return domain.process(
                RecordResult(notification_id=notification_id, status="SENT"),
                asynchronous=True,
                idempotency_key="k",
            )

    def test_failed_deferred_command_runs_again_on_repeat(
        self, test_domain, idempotency_store
    ):
        notification_id = _create_notification(test_domain)
        Probe.fail_with = RuntimeError("record failed")

        with pytest.raises(TransactionError):
            self._process(test_domain, notification_id)
        assert Probe.attempts == 1
        assert idempotency_store.entries["k"]["status"] == "error"

        Probe.fail_with = None
        self._process(test_domain, notification_id)

        assert Probe.attempts == 2
        assert len(_stored_commands(test_domain)) == 2
        assert _status(test_domain, notification_id) == "SENT"

    def test_succeeded_deferred_command_returns_the_cached_result(self, test_domain):
        notification_id = _create_notification(test_domain)
        self._process(test_domain, notification_id)
        assert Probe.attempts == 1

        result = self._process(test_domain, notification_id)

        assert result == "recorded-SENT"
        assert Probe.attempts == 1
        assert len(_stored_commands(test_domain)) == 1


@pytest.mark.postgresql
@pytest.mark.no_test_domain
@pytest.mark.parametrize("processing", [Processing.SYNC.value, Processing.ASYNC.value])
def test_record_step_conflict_on_postgresql(processing):
    # The same name as `test_domain`: a message type carries the domain name,
    # and these classes are registered there too.
    domain = Domain(name="Test")
    domain.config["databases"]["default"] = {
        "provider": "postgresql",
        "database_uri": POSTGRES_URI,
    }
    domain.config["command_processing"] = Processing.SYNC.value
    domain.config["event_processing"] = processing
    _register(domain)

    with domain.domain_context():
        provider = domain.providers["default"]
        provider._create_database_artifacts()
        try:
            with patch("protean.utils.mixins.time.sleep"):
                Probe.conflicts_left = 1
                notification_id = _start_dispatch(domain)

            assert Probe.channel == [notification_id]
            assert Probe.attempts == 2
            assert _status(domain, notification_id) == "SENT"
        finally:
            provider._drop_database_artifacts()
