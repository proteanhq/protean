"""Tests for StreamSubscription stream trimming.

A StreamSubscription trims the stream a batch came from after each batch, but
only when the broker declares ``STREAM_RETENTION``. It reads the flag once in
``initialize()``. A trim error is logged and swallowed.
"""

from uuid import uuid4

import pytest

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils.eventing import Message
from tests.shared import REDIS_URI


class Account(BaseAggregate):
    account_id = Identifier(identifier=True)
    name = String()


class AccountOpened(BaseEvent):
    account_id = Identifier(required=True)
    name = String()


class AccountEventHandler(BaseEventHandler):
    @handle(AccountOpened)
    def on_opened(self, event):
        pass


def _domain(broker: dict, **server: object) -> Domain:
    domain = Domain(name="RetentionTest")
    domain.config["brokers"]["default"] = broker
    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"
    domain.config["server"].update(server)
    domain.register(Account)
    domain.register(AccountOpened, part_of=Account)
    domain.register(AccountEventHandler, part_of=Account)
    domain.init(traverse=False)
    return domain


def _subscription(domain: Domain, **kwargs: object) -> StreamSubscription:
    return StreamSubscription(
        engine=Engine(domain, test_mode=True),
        stream_category=Account.meta_.stream_category,
        handler=AccountEventHandler,
        **kwargs,
    )


def _publish(domain: Domain, stream: str, count: int) -> None:
    broker = domain.brokers["default"]
    for i in range(count):
        event = AccountOpened(account_id=str(uuid4()), name=f"a{i}")
        broker.publish(stream, Message.from_domain_object(event).to_dict())


def _record_trims(domain: Domain) -> list[tuple[str, int]]:
    """Wrap the broker service's ``_trim`` and record each stream and its count."""
    broker = domain.brokers["default"]
    real_trim = broker._trim
    calls: list[tuple[str, int]] = []

    def _trim(stream: str) -> int:
        removed = real_trim(stream)
        calls.append((stream, removed))
        return removed

    broker._trim = _trim
    return calls


async def _process_one_batch(sub: StreamSubscription) -> None:
    """Run ``poll()`` until the first batch is processed, then stop."""
    process_batch = sub.process_batch

    async def _process_then_stop(messages, stream=None):
        result = await process_batch(messages, stream=stream)
        sub.keep_going = False
        return result

    sub.process_batch = _process_then_stop
    await sub.poll()


@pytest.mark.no_test_domain
class TestInlineBroker:
    async def test_processing_a_batch_does_not_call_trim(self):
        domain = _domain({"provider": "inline"})
        with domain.domain_context():
            sub = _subscription(domain)
            await sub.initialize()
            _publish(domain, sub.stream_category, 1)
            trims = _record_trims(domain)

            await _process_one_batch(sub)

            assert sub._trims_stream is False
            assert trims == []


@pytest.mark.redis
@pytest.mark.no_test_domain
class TestRedisBroker:
    """On Redis, each batch trims the stream it was read from.

    The batch is 250 entries so the approximate trim removes at least one whole
    100-entry node once the group has acknowledged them.
    """

    BATCH = 250

    @pytest.fixture
    def redis_domain(self):
        def make(**server: object) -> Domain:
            domain = _domain({"provider": "redis", "URI": f"{REDIS_URI}/11"}, **server)
            domain.brokers["default"].clear()
            return domain

        return make

    async def test_standard_mode_trims_the_primary_stream(self, redis_domain):
        domain = redis_domain()
        with domain.domain_context():
            sub = _subscription(domain, messages_per_tick=self.BATCH)
            await sub.initialize()
            _publish(domain, sub.stream_category, self.BATCH)
            trims = _record_trims(domain)

            await _process_one_batch(sub)

            assert sub._trims_stream is True
            assert len(trims) == 1
            stream, removed = trims[0]
            assert stream == sub.stream_category
            assert removed > 0
            client = domain.brokers["default"].get_connection()
            assert client.xlen(sub.stream_category) == self.BATCH - removed
            domain.brokers["default"].clear()

    async def test_priority_lanes_trim_the_backfill_stream(self, redis_domain):
        domain = redis_domain(
            priority_lanes={"enabled": True, "backfill_suffix": "backfill"}
        )
        with domain.domain_context():
            sub = _subscription(domain, messages_per_tick=self.BATCH)
            await sub.initialize()
            _publish(domain, sub.backfill_stream, self.BATCH)
            trims = _record_trims(domain)

            await _process_one_batch(sub)

            assert len(trims) == 1
            stream, removed = trims[0]
            assert stream == sub.backfill_stream
            assert removed > 0
            domain.brokers["default"].clear()

    async def test_priority_lanes_trim_the_primary_stream(self, redis_domain):
        domain = redis_domain(
            priority_lanes={"enabled": True, "backfill_suffix": "backfill"}
        )
        with domain.domain_context():
            sub = _subscription(domain, messages_per_tick=self.BATCH)
            await sub.initialize()
            _publish(domain, sub.stream_category, self.BATCH)
            trims = _record_trims(domain)

            await _process_one_batch(sub)

            assert len(trims) == 1
            stream, removed = trims[0]
            assert stream == sub.stream_category
            assert removed > 0
            domain.brokers["default"].clear()


class _RaisingBroker:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _trim(self, stream: str) -> int:
        self.calls.append(stream)
        raise RuntimeError("simulated trim failure")


@pytest.mark.no_test_domain
class TestMaybeTrim:
    @pytest.fixture
    def sub(self):
        domain = _domain({"provider": "inline"})
        with domain.domain_context():
            yield _subscription(domain)

    async def test_trim_error_is_swallowed(self, sub, caplog):
        broker = _RaisingBroker()
        sub.broker = broker
        sub._trims_stream = True

        await sub._maybe_trim("account")

        assert broker.calls == ["account"]
        assert "Error trimming stream account: simulated trim failure" in caplog.text

    async def test_no_trim_without_the_capability(self, sub):
        broker = _RaisingBroker()
        sub.broker = broker

        await sub._maybe_trim("account")

        assert sub._trims_stream is False
        assert broker.calls == []

    async def test_no_trim_without_broker(self, sub, caplog):
        sub._trims_stream = True
        sub.broker = None

        await sub._maybe_trim("account")

        # Without the guard, ``None._trim`` raises and the handler logs it.
        assert "Error trimming stream" not in caplog.text
