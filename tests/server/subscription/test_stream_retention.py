"""Tests for StreamSubscription stream-retention wiring.

Covers how a StreamSubscription threads ``retention_maxlen`` from config into
the ``_maybe_trim`` helper it calls after each batch: retention off means the
broker's ``trim`` is never called, retention on trims the exact stream the batch
came from, and a trim error is logged and swallowed rather than propagated.
"""

import pytest

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.server.subscription.profiles import (
    SubscriptionConfig,
    SubscriptionProfile,
)
from protean.server.subscription.stream_subscription import StreamSubscription


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


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(AccountOpened, part_of=Account)
    test_domain.register(AccountEventHandler, part_of=Account)
    test_domain.init(traverse=False)


@pytest.fixture
def engine(test_domain):
    with test_domain.domain_context():
        return Engine(test_domain, test_mode=True)


class _TrimRecorder:
    """A broker stand-in that records trim() calls (and can raise on demand)."""

    def __init__(self, *, raise_error: bool = False) -> None:
        self.calls: list[tuple[str, int]] = []
        self.raise_error = raise_error

    def trim(self, stream: str, maxlen: int) -> int:
        self.calls.append((stream, maxlen))
        if self.raise_error:
            raise RuntimeError("simulated trim failure")
        return 0


def _subscription(engine, **kwargs) -> StreamSubscription:
    return StreamSubscription(
        engine=engine,
        stream_category="account",
        handler=AccountEventHandler,
        **kwargs,
    )


class TestRetentionMaxlenWiring:
    """retention_maxlen flows from config into the subscription."""

    def test_default_retention_is_none(self, engine, test_domain):
        with test_domain.domain_context():
            sub = _subscription(engine)
        assert sub.retention_maxlen is None

    def test_explicit_retention_is_stored(self, engine, test_domain):
        with test_domain.domain_context():
            sub = _subscription(engine, retention_maxlen=250)
        assert sub.retention_maxlen == 250

    def test_from_config_forwards_retention(self, engine, test_domain):
        """from_config carries retention_maxlen off the SubscriptionConfig."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)
        with test_domain.domain_context():
            sub = StreamSubscription.from_config(
                engine, "account", AccountEventHandler, config
            )
        assert sub.retention_maxlen == config.retention_maxlen == 100_000

    def test_from_config_forwards_none_for_projection_like(self, engine, test_domain):
        """A config with retention off yields a subscription with trimming off."""
        config = SubscriptionConfig(retention_maxlen=None)
        with test_domain.domain_context():
            sub = StreamSubscription.from_config(
                engine, "account", AccountEventHandler, config
            )
        assert sub.retention_maxlen is None


class TestMaybeTrim:
    """_maybe_trim only trims when retention is enabled."""

    async def test_no_trim_when_retention_off(self, engine, test_domain):
        """With retention_maxlen=None the broker's trim is never called."""
        with test_domain.domain_context():
            sub = _subscription(engine, retention_maxlen=None)
        recorder = _TrimRecorder()
        sub.broker = recorder

        await sub._maybe_trim("account")

        assert recorder.calls == []

    async def test_trims_named_stream_when_retention_on(self, engine, test_domain):
        """With retention on, trim runs against the exact stream passed in."""
        with test_domain.domain_context():
            sub = _subscription(engine, retention_maxlen=500)
        recorder = _TrimRecorder()
        sub.broker = recorder

        await sub._maybe_trim("account:backfill")

        assert recorder.calls == [("account:backfill", 500)]

    async def test_no_trim_without_broker(self, engine, test_domain):
        """_maybe_trim is a no-op (no error) when the broker is not set."""
        with test_domain.domain_context():
            sub = _subscription(engine, retention_maxlen=500)
        sub.broker = None

        # Should simply return without raising.
        await sub._maybe_trim("account")

    async def test_trim_error_is_swallowed(self, engine, test_domain):
        """A trim failure is logged and swallowed, not propagated to the caller."""
        with test_domain.domain_context():
            sub = _subscription(engine, retention_maxlen=500)
        recorder = _TrimRecorder(raise_error=True)
        sub.broker = recorder

        # The RuntimeError raised inside trim must not surface here.
        await sub._maybe_trim("account")

        assert recorder.calls == [("account", 500)]
