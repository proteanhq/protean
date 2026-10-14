from protean import Domain
from protean.fields import Identifier, String
from protean.utils.globals import current_domain

domain = Domain(name="Catalogue")
domain.config["message_processing"] = "sync"


@domain.aggregate
class Product:
    product_id: Identifier(identifier=True)
    name: String()


@domain.event(part_of=Product)
class ProductBecameUnavailable:
    product_id: Identifier(required=True)
    reason: String(required=True)


# --8<-- [start:subscriber]
@domain.subscriber(stream="inventory-external")
class ExternalInventorySubscriber:
    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type")

        if event_type == "StockDepleted":
            repo = current_domain.repository_for(Product)
            product = repo.get(payload["sku"])

            product.raise_(
                ProductBecameUnavailable(
                    product_id=product.product_id,
                    reason="external_stock_depleted",
                )
            )
            repo.add(product)


# --8<-- [end:subscriber]
