"""Tests for wide event domain context enrichment.

Verifies that:
- Aggregate type and ID are populated
- Events raised are tracked
- Repository operations are counted
- UoW outcome is committed on success
- UoW outcome is rolled_back on failure
- Query handlers report no_uow
"""

import logging
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle, read


# --- Domain elements ---


class Product(BaseAggregate):
    product_id = Identifier(identifier=True)
    name = String()
    status = String(default="draft")

    def publish(self) -> None:
        self.status = "published"
        self.raise_(ProductPublished(product_id=self.product_id, name=self.name))

    def archive(self) -> None:
        self.status = "archived"
        self.raise_(ProductArchived(product_id=self.product_id))


class ProductPublished(BaseEvent):
    product_id = Identifier()
    name = String()


class ProductArchived(BaseEvent):
    product_id = Identifier()


class PublishProduct(BaseCommand):
    product_id = Identifier(identifier=True)
    name = String()


class PublishAndArchive(BaseCommand):
    """Command that raises two events."""

    product_id = Identifier(identifier=True)
    name = String()


class FailingPublish(BaseCommand):
    product_id = Identifier(identifier=True)


class PublishProductHandler(BaseCommandHandler):
    @handle(PublishProduct)
    def handle_publish(self, command: PublishProduct) -> None:
        repo = current_domain.repository_for(Product)
        product = Product(product_id=command.product_id, name=command.name)
        product.publish()
        repo.add(product)


class PublishAndArchiveHandler(BaseCommandHandler):
    @handle(PublishAndArchive)
    def handle_publish_and_archive(self, command: PublishAndArchive) -> None:
        repo = current_domain.repository_for(Product)
        product = Product(product_id=command.product_id, name=command.name)
        product.publish()
        product.archive()
        repo.add(product)


class FailingPublishHandler(BaseCommandHandler):
    @handle(FailingPublish)
    def handle_failing(self, command: FailingPublish) -> None:
        raise RuntimeError("Publish failed")


class LoadAndSaveHandler(BaseCommandHandler):
    """Handler that performs both get() and add() operations."""

    @handle(PublishProduct)
    def handle_publish(self, command: PublishProduct) -> None:
        repo = current_domain.repository_for(Product)
        # First save
        product = Product(product_id=command.product_id, name=command.name)
        repo.add(product)
        # Then load twice
        repo.get(command.product_id)
        repo.get(command.product_id)


class ProductEventHandler(BaseEventHandler):
    @handle(ProductPublished)
    def on_published(self, event: ProductPublished) -> None:
        pass


class ProductSummary(BaseProjection):
    product_id = Identifier(identifier=True)
    name = String()


class GetProductById(BaseQuery):
    product_id = Identifier(required=True)


class ProductQueryHandler(BaseQueryHandler):
    @read(GetProductById)
    def get_by_id(self, query: GetProductById) -> dict:
        return {"product_id": query.product_id, "name": "Test Product"}


def _access_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "protean.access"]


class TestAggregateTypeAndIdPopulated:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Product)
        test_domain.register(ProductPublished, part_of=Product)
        test_domain.register(ProductArchived, part_of=Product)
        test_domain.register(PublishProduct, part_of=Product)
        test_domain.register(PublishProductHandler, part_of=Product)
        test_domain.register(ProductEventHandler, part_of=Product)
        test_domain.init(traverse=False)

    def test_aggregate_type_and_id_populated(self, test_domain, caplog):
        product_id = str(uuid4())
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(PublishProduct(product_id=product_id, name="Widget"))

        records = _access_records(caplog)
        cmd_records = [r for r in records if r.kind == "command"]
        assert len(cmd_records) >= 1

        record = cmd_records[0]
        assert record.aggregate == "Product"
        assert record.aggregate_id == product_id


class TestEventsRaisedTracked:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Product)
        test_domain.register(ProductPublished, part_of=Product)
        test_domain.register(ProductArchived, part_of=Product)
        test_domain.register(PublishAndArchive, part_of=Product)
        test_domain.register(PublishAndArchiveHandler, part_of=Product)
        test_domain.init(traverse=False)

    def test_events_raised_tracked(self, test_domain, caplog):
        product_id = str(uuid4())
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                PublishAndArchive(product_id=product_id, name="Archive Test")
            )

        records = _access_records(caplog)
        cmd_records = [r for r in records if r.kind == "command"]
        assert len(cmd_records) >= 1

        record = cmd_records[0]
        assert "ProductPublished" in record.events_raised
        assert "ProductArchived" in record.events_raised
        assert record.events_raised_count == 2


class TestRepoOperationsCounted:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Product)
        test_domain.register(ProductPublished, part_of=Product)
        test_domain.register(ProductArchived, part_of=Product)
        test_domain.register(PublishProduct, part_of=Product)
        test_domain.register(LoadAndSaveHandler, part_of=Product)
        test_domain.init(traverse=False)

    def test_repo_operations_counted(self, test_domain, caplog):
        product_id = str(uuid4())
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                PublishProduct(product_id=product_id, name="Count Test")
            )

        records = _access_records(caplog)
        cmd_records = [r for r in records if r.kind == "command"]
        assert len(cmd_records) >= 1

        record = cmd_records[0]
        assert record.repo_operations["loads"] == 2
        assert record.repo_operations["saves"] >= 1


class TestUoWCommittedOnSuccess:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Product)
        test_domain.register(ProductPublished, part_of=Product)
        test_domain.register(ProductArchived, part_of=Product)
        test_domain.register(PublishProduct, part_of=Product)
        test_domain.register(PublishProductHandler, part_of=Product)
        test_domain.register(ProductEventHandler, part_of=Product)
        test_domain.init(traverse=False)

    def test_uow_committed_on_success(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                PublishProduct(product_id=str(uuid4()), name="Commit Test")
            )

        records = _access_records(caplog)
        cmd_records = [r for r in records if r.kind == "command"]
        assert len(cmd_records) >= 1
        assert cmd_records[0].uow_outcome == "committed"


class TestUoWRolledBackOnFailure:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Product)
        test_domain.register(ProductPublished, part_of=Product)
        test_domain.register(ProductArchived, part_of=Product)
        test_domain.register(FailingPublish, part_of=Product)
        test_domain.register(FailingPublishHandler, part_of=Product)
        test_domain.init(traverse=False)

    def test_uow_rolled_back_on_failure(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            with pytest.raises(RuntimeError, match="Publish failed"):
                test_domain.process(FailingPublish(product_id=str(uuid4())))

        records = _access_records(caplog)
        assert len(records) >= 1
        assert records[0].uow_outcome == "rolled_back"


class TestNoUoWForQuery:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(ProductSummary)
        test_domain.register(GetProductById, part_of=ProductSummary)
        test_domain.register(ProductQueryHandler, part_of=ProductSummary)
        test_domain.init(traverse=False)

    def test_no_uow_for_query(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.dispatch(GetProductById(product_id="prod-1"))

        records = _access_records(caplog)
        assert len(records) >= 1
        assert records[0].uow_outcome == "no_uow"
