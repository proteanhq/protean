# --8<-- [start:elements]
from protean import Domain, current_domain
from protean.core.projector import on
from protean.fields import Identifier, Integer, String

domain = Domain(name="Warehouse")


@domain.aggregate
class InventoryItem:
    sku: String(required=True)
    quantity: Integer(default=0)


@domain.event(part_of=InventoryItem)
class StockDepleted:
    item_id: Identifier(required=True)
    sku: String(required=True)


@domain.projection
class LowStockReport:
    item_id: Identifier(identifier=True)
    sku: String()
    status: String()


# --8<-- [end:elements]


# --8<-- [start:projector]
@domain.projector(
    projector_for=LowStockReport,
    aggregates=[InventoryItem],
    retries=8,
    backoff="exponential",
    retry_exceptions=["protean.exceptions.TransactionError"],
)
class LowStockReportProjector:
    @on(StockDepleted)
    def on_stock_depleted(self, event: StockDepleted):
        repository = current_domain.repository_for(LowStockReport)
        report = repository.get_or_none(event.item_id) or LowStockReport(
            item_id=event.item_id, sku=event.sku
        )
        report.status = "OUT_OF_STOCK"
        repository.add(report)


# --8<-- [end:projector]
