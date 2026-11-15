"""Order of the calls ``OutboxProcessor`` makes per message in a batch.

``process_batch`` publishes each row to the broker, then records the outcome in
its own transaction. ``specs/OutboxTrace.tla`` models that order. Rows with no
hold-back group are worked through in the order the batch gives them; rows in
one group are put in commit order, and the later rows of a group whose row
failed are released instead of published. These tests use rows with no group.
They record the publish and the committed mark of every row into one list and
pin the order, so a change that reorders the two goes red.
"""

import pytest

from protean.port.broker import BrokerCapabilities
from protean.server import Engine
from protean.server.outbox_processor import OutboxProcessor
from protean.utils import outbox_trace
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox, OutboxStatus

pytestmark = pytest.mark.database

CATEGORY = "test::counter"


class _SelectiveBroker:
    """Broker stub that fails the message ids it is given and accepts the rest."""

    name = "default"

    def __init__(self, fail_ids: set[str]) -> None:
        self.fail_ids = fail_ids

    def has_capability(self, capability: BrokerCapabilities) -> bool:
        return False

    def publish(self, stream: str, message: dict) -> str:
        if message["metadata"]["headers"]["id"] in self.fail_ids:
            raise RuntimeError("broker down")
        return "broker-msg-id"


@pytest.fixture
def outbox_domain(test_domain):
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"
    test_domain.init(traverse=False)
    return test_domain


def _row(label: str) -> Outbox:
    metadata = Metadata(
        headers=MessageHeaders(id=label, type="Test.Bumped.v1", stream=CATEGORY),
        domain=DomainMeta(stream_category=CATEGORY),
    )
    return Outbox.create_message(
        message_id=label,
        stream_name=f"{CATEGORY}-1",
        message_type="Test.Bumped.v1",
        data={"label": label},
        metadata=metadata,
    )


async def _claimed_batch(
    domain, labels: list[str], fail_ids: set[str]
) -> tuple[OutboxProcessor, dict[str, Outbox]]:
    """Store one row per label, claim them all, and return the rows by label."""
    repo = domain._get_outbox_repo("default")
    for label in labels:
        repo.add(_row(label))
    processor = OutboxProcessor(
        Engine(domain, test_mode=True), "default", "default", worker_id="w1"
    )
    await processor.initialize()
    processor.broker = _SelectiveBroker(fail_ids)
    batch = await processor.get_next_batch_of_messages()
    return processor, {row.message_id: row for row in batch}


def _steps(events: list[dict], rows: dict[str, Outbox]) -> list[tuple[str, str, str]]:
    labels = {str(row.id): label for label, row in rows.items()}
    return [
        (event["action"], labels[event["message"]], event["outcome"])
        for event in events
    ]


@pytest.mark.asyncio
async def test_each_row_is_published_before_its_status_is_marked(outbox_domain):
    processor, rows = await _claimed_batch(outbox_domain, ["a", "b", "c"], {"b"})
    assert len(rows) == 3

    with outbox_trace.capture() as events:
        successful = await processor.process_batch([rows["a"], rows["b"], rows["c"]])

    assert successful == 2
    assert _steps(events, rows) == [
        ("publish", "a", "ok"),
        ("mark", "a", OutboxStatus.PUBLISHED.value),
        ("publish", "b", "fail"),
        ("mark", "b", OutboxStatus.FAILED.value),
        ("publish", "c", "ok"),
        ("mark", "c", OutboxStatus.PUBLISHED.value),
    ]


@pytest.mark.asyncio
async def test_rows_with_no_partition_key_are_processed_in_the_order_given(
    outbox_domain,
):
    processor, rows = await _claimed_batch(outbox_domain, ["a", "b", "c"], set())
    assert len(rows) == 3

    with outbox_trace.capture() as events:
        successful = await processor.process_batch([rows["c"], rows["a"], rows["b"]])

    assert successful == 3
    assert _steps(events, rows) == [
        ("publish", "c", "ok"),
        ("mark", "c", OutboxStatus.PUBLISHED.value),
        ("publish", "a", "ok"),
        ("mark", "a", OutboxStatus.PUBLISHED.value),
        ("publish", "b", "ok"),
        ("mark", "b", OutboxStatus.PUBLISHED.value),
    ]
