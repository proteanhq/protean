"""Two outbox processors keep a partition key's events in order on Redis.

Two ``OutboxProcessor`` instances share a PostgreSQL outbox and publish to a
Redis broker that partitions streams. One aggregate commits ten events whose
category a ``sequential_by`` handler partitions, and the first processor fails
to publish an early one. While that row waits for its retry, neither processor
may publish the later rows, so the partition stream still reads the events in
commit order.
"""

import json
from datetime import timedelta

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain
from protean.fields import Identifier, Integer
from protean.server.outbox_processor import OutboxProcessor
from protean.utils.mixins import handle
from protean.utils.outbox import OutboxStatus
from tests.shared import POSTGRES_URI, REDIS_URI

pytestmark = [pytest.mark.postgresql, pytest.mark.redis, pytest.mark.no_test_domain]

VERSIONS = 10
FAILING_VERSION = 1


class Restocked(BaseEvent):
    product_id = Identifier(required=True)
    version = Integer(required=True)


class Product(BaseAggregate):
    stock = Integer(default=0)

    def restock(self) -> None:
        self.raise_(Restocked(product_id=self.id, version=self.stock))
        self.stock += 1


class StockProjector(BaseEventHandler):
    @handle(Restocked)
    def on_restocked(self, event: Restocked) -> None:
        pass


class FailOnceBroker:
    """Wraps the real broker and fails the first publish of one version."""

    def __init__(self, inner, version: int) -> None:
        self._inner = inner
        self._version = version
        self.failed = False

    def publish(self, stream: str, message: dict) -> str:
        if not self.failed and message["data"]["version"] == self._version:
            self.failed = True
            raise RuntimeError("broker down")
        return self._inner.publish(stream, message)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class FakeEmitter:
    def emit(self, **kwargs) -> None:
        pass


class FakeEngine:
    def __init__(self, domain: Domain) -> None:
        self.domain = domain
        self.loop = None
        self.emitter = FakeEmitter()


@pytest.fixture
def domain():
    domain = Domain(name="HoldBackRepro")
    domain.config["databases"]["default"] = {
        "provider": "postgresql",
        "database_uri": POSTGRES_URI,
    }
    domain.config["brokers"]["default"] = {
        "provider": "redis",
        "URI": f"{REDIS_URI}/12",
    }
    domain.config["enable_outbox"] = True
    domain.config["event_processing"] = "async"
    domain.config["server"]["default_subscription_type"] = "stream"
    domain._initialize()
    domain.register(Product)
    domain.register(Restocked, part_of=Product)
    domain.register(StockProjector, part_of=Product, sequential_by="product_id")
    domain.init(traverse=False)

    with domain.domain_context():
        provider = domain.providers["default"]
        provider._create_database_artifacts()
        domain.brokers["default"]._data_reset()
        try:
            yield domain
        finally:
            domain.brokers["default"]._data_reset()
            provider._drop_database_artifacts()


async def _processor(domain: Domain, worker_id: str) -> OutboxProcessor:
    processor = OutboxProcessor(
        FakeEngine(domain),
        "default",
        "default",
        messages_per_tick=3,
        worker_id=worker_id,
    )
    await processor.initialize()
    return processor


def _commit_events(domain: Domain) -> str:
    repo = domain.repository_for(Product)
    product = Product()
    with UnitOfWork():
        repo.add(product)
    for _ in range(VERSIONS):
        with UnitOfWork():
            current = repo.get(product.id)
            current.restock()
            repo.add(current)
    return product.id


def _make_failed_row_due(domain: Domain) -> None:
    outbox_repo = domain._get_outbox_repo("default")
    [row] = outbox_repo._dao.query.filter(status=OutboxStatus.FAILED.value).all().items
    row.next_retry_at = domain.clock.now() - timedelta(seconds=1)
    outbox_repo.add(row)


def _versions_on(domain: Domain, stream: str) -> list[int]:
    client = domain.brokers["default"]._client
    return [
        json.loads(fields[b"data"])["data"]["version"]
        for _, fields in client.xrange(stream)
    ]


@pytest.mark.asyncio
async def test_two_processors_publish_a_key_in_commit_order_despite_a_failure(
    domain,
):
    product_id = _commit_events(domain)
    first = await _processor(domain, "worker-1")
    second = await _processor(domain, "worker-2")
    first.broker = FailOnceBroker(first.broker, FAILING_VERSION)

    # The first batch publishes version 0 and fails version 1.
    await first.process_batch(await first.get_next_batch_of_messages())
    assert first.broker.failed

    # Both processors keep polling while version 1 waits for its retry.
    for processor in (second, first, second):
        await processor.process_batch(await processor.get_next_batch_of_messages())

    stream = f"{Product.meta_.stream_category}:{product_id}"
    assert _versions_on(domain, stream) == [0]

    _make_failed_row_due(domain)
    for _ in range(VERSIONS):
        for processor in (second, first):
            await processor.process_batch(await processor.get_next_batch_of_messages())

    assert _versions_on(domain, stream) == list(range(VERSIONS))
