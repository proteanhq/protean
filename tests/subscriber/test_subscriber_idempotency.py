"""Consume-side idempotency for broker subscribers (ADR-0017).

A subscriber registered with ``idempotent=True`` records a
``(metadata.headers.id, subscriber fqn)`` marker in its ``provider``, in the same
UnitOfWork as its writes, so a redelivered payload is applied once. The engine
path (``Engine.handle_broker_message``) and the sync path
(``BaseBroker.publish``) behave the same.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.exceptions import ConfigurationError, InsufficientDataError
from protean.fields import String
from protean.server import Engine
from protean.utils import fqn
from protean.utils.consume_idempotency import cleanup_processed_messages
from protean.utils.globals import current_domain
from tests.shared import FrozenClock

STREAM = "payments"
MESSAGE_ID = "billing::payment-42-0"


class Receipt(BaseAggregate):
    reference = String(max_length=50)


class RecordReceipt(BaseSubscriber):
    calls: list[dict] = []

    def __call__(self, payload: dict) -> None:
        type(self).calls.append(payload)
        current_domain.repository_for(Receipt).add(
            Receipt(reference=payload["reference"])
        )


class AuditReceipt(BaseSubscriber):
    calls: list[dict] = []

    def __call__(self, payload: dict) -> None:
        type(self).calls.append(payload)


class SaveThenFail(BaseSubscriber):
    calls: list[dict] = []

    def __call__(self, payload: dict) -> None:
        type(self).calls.append(payload)
        current_domain.repository_for(Receipt).add(
            Receipt(reference=payload["reference"])
        )
        raise RuntimeError("downstream failure")


class RecordingErrors(BaseSubscriber):
    calls: list[dict] = []
    errors: list[Exception] = []

    def __call__(self, payload: dict) -> None:
        type(self).calls.append(payload)

    @classmethod
    def handle_error(cls, exc: Exception, message: dict) -> None:
        cls.errors.append(exc)


@pytest.fixture(autouse=True)
def _reset_state(test_domain):
    # The markers and receipts live in the memory provider, whatever database
    # the run targets: these tests are about delivery, not storage adapters.
    test_domain.config["databases"]["default"] = {"provider": "memory"}
    for cls in (RecordReceipt, AuditReceipt, SaveThenFail, RecordingErrors):
        cls.calls = []
    RecordingErrors.errors = []
    yield


def _payload(message_id: str | None = MESSAGE_ID, reference: str = "r-1") -> dict:
    payload: dict = {"reference": reference}
    if message_id is not None:
        payload["metadata"] = {"headers": {"id": message_id}}
    return payload


def _register(test_domain, *subscribers, **opts) -> None:
    test_domain.register(Receipt)
    for subscriber_cls in subscribers:
        test_domain.register(subscriber_cls, stream=STREAM, **opts)
    test_domain.init(traverse=False)


def _deliver(test_domain, subscriber_cls, payload: dict) -> bool:
    engine = Engine(domain=test_domain, test_mode=True)
    return asyncio.run(
        engine.handle_broker_message(
            subscriber_cls, payload, message_id="broker-1", stream=STREAM
        )
    )


def _publish(test_domain, payload: dict) -> None:
    test_domain.config["message_processing"] = Processing.SYNC.value
    test_domain.brokers["default"].publish(STREAM, payload)


def _receipts(test_domain) -> list:
    return test_domain.repository_for(Receipt)._dao.query.all().items


def _is_marked(test_domain, provider: str, subscriber_cls, message_id: str) -> bool:
    repo = test_domain._get_processed_message_repo(provider)
    return repo.is_processed(message_id, fqn(subscriber_cls))


class TestOptions:
    def test_defaults_leave_a_subscriber_non_idempotent_on_the_default_provider(
        self, test_domain
    ):
        _register(test_domain, AuditReceipt)

        assert AuditReceipt.meta_.idempotent is False
        assert AuditReceipt.meta_.provider == "default"

    def test_options_register_on_the_subscriber(self, test_domain):
        test_domain.config["databases"]["other"] = {"provider": "memory"}
        _register(test_domain, AuditReceipt, idempotent=True, provider="other")

        assert AuditReceipt.meta_.idempotent is True
        assert AuditReceipt.meta_.provider == "other"


class TestMarkerStorage:
    def test_marker_is_written_to_the_default_provider(self, test_domain):
        _register(test_domain, RecordReceipt, idempotent=True)

        assert _deliver(test_domain, RecordReceipt, _payload()) is True

        assert _is_marked(test_domain, "default", RecordReceipt, MESSAGE_ID)
        assert [r.reference for r in _receipts(test_domain)] == ["r-1"]

    def test_marker_is_written_to_the_named_provider_only(self, test_domain):
        test_domain.config["databases"]["other"] = {"provider": "memory"}
        _register(test_domain, AuditReceipt, idempotent=True, provider="other")

        assert _deliver(test_domain, AuditReceipt, _payload()) is True

        assert _is_marked(test_domain, "other", AuditReceipt, MESSAGE_ID)
        assert not _is_marked(test_domain, "default", AuditReceipt, MESSAGE_ID)

    def test_marker_tables_exist_after_init_for_an_only_subscriber_domain(
        self, test_domain
    ):
        _register(test_domain, AuditReceipt, idempotent=True)

        assert "default" in test_domain._infrastructure.processed_message_repos

    def test_no_marker_tables_without_an_idempotent_consumer(self, test_domain):
        _register(test_domain, AuditReceipt)

        assert test_domain.has_idempotent_consumers is False
        assert test_domain._infrastructure.processed_message_repos == {}

    def test_marker_tables_exist_for_every_named_provider(self, test_domain):
        test_domain.config["databases"]["other"] = {"provider": "memory"}
        test_domain.register(Receipt)
        test_domain.register(RecordReceipt, stream=STREAM, idempotent=True)
        test_domain.register(
            AuditReceipt, stream=STREAM, idempotent=True, provider="other"
        )
        test_domain.init(traverse=False)

        repos = test_domain._infrastructure.processed_message_repos
        assert {"default", "other"} <= set(repos)

    def test_cleanup_prunes_an_old_subscriber_marker(self, test_domain):
        _register(test_domain, AuditReceipt, idempotent=True)
        clock = FrozenClock(datetime.now(UTC))
        test_domain.clock = clock
        _deliver(test_domain, AuditReceipt, _payload())
        assert _is_marked(test_domain, "default", AuditReceipt, MESSAGE_ID)

        clock.advance(timedelta(days=8))

        assert cleanup_processed_messages(test_domain) == 1
        assert not _is_marked(test_domain, "default", AuditReceipt, MESSAGE_ID)


class TestProviderValidation:
    def test_init_rejects_an_unknown_provider(self, test_domain):
        test_domain.register(
            AuditReceipt, stream=STREAM, idempotent=True, provider="missing"
        )

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert "AuditReceipt" in str(exc.value)
        assert "`missing`" in str(exc.value)
        assert "not configured" in str(exc.value)

    def test_init_rejects_an_unmanaged_provider(self, test_domain):
        test_domain.config["databases"]["legacy"] = {
            "provider": "memory",
            "managed": False,
        }
        test_domain.register(
            AuditReceipt, stream=STREAM, idempotent=True, provider="legacy"
        )

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert "AuditReceipt" in str(exc.value)
        assert "`legacy`" in str(exc.value)
        assert "not managed" in str(exc.value)

    def test_init_ignores_the_provider_of_a_non_idempotent_subscriber(
        self, test_domain
    ):
        test_domain.register(AuditReceipt, stream=STREAM, provider="missing")

        test_domain.init(traverse=False)

        assert AuditReceipt.meta_.provider == "missing"


class TestEngineDelivery:
    def test_redelivery_is_applied_once(self, test_domain):
        _register(test_domain, RecordReceipt, idempotent=True)

        assert _deliver(test_domain, RecordReceipt, _payload()) is True
        assert _deliver(test_domain, RecordReceipt, _payload()) is True

        assert len(RecordReceipt.calls) == 1
        assert len(_receipts(test_domain)) == 1

    def test_redelivery_is_applied_twice_without_the_option(self, test_domain):
        _register(test_domain, RecordReceipt)

        _deliver(test_domain, RecordReceipt, _payload())
        _deliver(test_domain, RecordReceipt, _payload())

        assert len(RecordReceipt.calls) == 2
        assert len(_receipts(test_domain)) == 2

    def test_a_raise_rolls_back_the_writes_and_leaves_no_marker(self, test_domain):
        _register(test_domain, SaveThenFail, idempotent=True)

        assert _deliver(test_domain, SaveThenFail, _payload()) is False

        assert _receipts(test_domain) == []
        assert not _is_marked(test_domain, "default", SaveThenFail, MESSAGE_ID)

        assert _deliver(test_domain, SaveThenFail, _payload()) is False
        assert len(SaveThenFail.calls) == 2

    def test_two_subscribers_on_one_stream_each_apply_once(self, test_domain):
        _register(test_domain, RecordReceipt, AuditReceipt, idempotent=True)

        for _ in range(2):
            _deliver(test_domain, RecordReceipt, _payload())
            _deliver(test_domain, AuditReceipt, _payload())

        assert len(RecordReceipt.calls) == 1
        assert len(AuditReceipt.calls) == 1
        assert fqn(RecordReceipt) != fqn(AuditReceipt)
        assert _is_marked(test_domain, "default", RecordReceipt, MESSAGE_ID)
        assert _is_marked(test_domain, "default", AuditReceipt, MESSAGE_ID)

    @pytest.mark.parametrize(
        "payload",
        [
            {"reference": "r-1"},
            {"reference": "r-1", "metadata": {"headers": {}}},
            {"reference": "r-1", "metadata": {"headers": {"id": "   "}}},
        ],
        ids=["no-metadata", "headers-without-id", "blank-id"],
    )
    def test_a_payload_without_an_id_is_an_error(self, test_domain, caplog, payload):
        _register(test_domain, RecordingErrors, idempotent=True)

        with caplog.at_level(logging.ERROR):
            # The broker delivery id is passed and must not stand in as the key.
            result = _deliver(test_domain, RecordingErrors, payload)

        assert result is False
        assert RecordingErrors.calls == []
        assert len(RecordingErrors.errors) == 1
        assert isinstance(RecordingErrors.errors[0], InsufficientDataError)
        messages = [
            r.getMessage() for r in caplog.records if r.levelno == logging.ERROR
        ]
        assert any(
            fqn(RecordingErrors) in m and "metadata.headers.id" in m for m in messages
        )
        assert not _is_marked(test_domain, "default", RecordingErrors, "broker-1")

    def test_a_payload_without_an_id_runs_without_the_option(self, test_domain):
        _register(test_domain, RecordingErrors)

        assert _deliver(test_domain, RecordingErrors, {"reference": "r-1"}) is True

        assert RecordingErrors.calls == [{"reference": "r-1"}]


class TestSyncDelivery:
    def test_republish_is_applied_once(self, test_domain):
        _register(test_domain, RecordReceipt, idempotent=True)

        _publish(test_domain, _payload())
        _publish(test_domain, _payload())

        assert len(RecordReceipt.calls) == 1
        assert len(_receipts(test_domain)) == 1
        assert _is_marked(test_domain, "default", RecordReceipt, MESSAGE_ID)

    def test_republish_is_applied_twice_without_the_option(self, test_domain):
        _register(test_domain, RecordReceipt)

        _publish(test_domain, _payload())
        _publish(test_domain, _payload())

        assert len(RecordReceipt.calls) == 2

    def test_a_raise_rolls_back_the_writes_and_leaves_no_marker(self, test_domain):
        _register(test_domain, SaveThenFail, idempotent=True)

        with pytest.raises(RuntimeError, match="downstream failure"):
            _publish(test_domain, _payload())

        assert _receipts(test_domain) == []
        assert not _is_marked(test_domain, "default", SaveThenFail, MESSAGE_ID)

    def test_a_payload_without_an_id_raises(self, test_domain):
        _register(test_domain, RecordingErrors, idempotent=True)

        with pytest.raises(InsufficientDataError, match=r"metadata\.headers\.id"):
            _publish(test_domain, {"reference": "r-1"})

        assert RecordingErrors.calls == []

    def test_a_payload_without_an_id_runs_without_the_option(self, test_domain):
        _register(test_domain, RecordingErrors)

        _publish(test_domain, {"reference": "r-1"})

        assert RecordingErrors.calls == [{"reference": "r-1"}]
