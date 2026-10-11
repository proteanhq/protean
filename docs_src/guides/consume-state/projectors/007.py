# --8<-- [start:elements]
import logging

from protean import Domain, current_domain
from protean.core.projector import on
from protean.exceptions import ObjectNotFoundError
from protean.fields import Float, Identifier, Integer, String

logger = logging.getLogger(__name__)

domain = Domain(name="Catalog")


@domain.aggregate
class Product:
    name: String(required=True)
    price: Float(required=True)


@domain.event(part_of=Product)
class ProductAdded:
    product_id: Identifier(required=True)
    name: String(required=True)
    price: Float(required=True)
    stock_quantity: Integer(default=0)


@domain.projection
class ProductInventory:
    product_id: Identifier(identifier=True)
    name: String(max_length=50)
    price: Float()
    stock_quantity: Integer(default=0)


# --8<-- [end:elements]


# --8<-- [start:projector]
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        try:
            repository = current_domain.repository_for(ProductInventory)

            # Check if inventory already exists
            try:
                repository.get(event.product_id)
                # Handle duplicate case
                return
            except ObjectNotFoundError:
                pass  # Expected case - create new inventory

            inventory = ProductInventory(
                product_id=event.product_id,
                name=event.name,
                price=event.price,
                stock_quantity=event.stock_quantity,
            )

            repository.add(inventory)

        except Exception as e:
            # Log error and potentially raise for retry mechanisms
            logger.error(f"Failed to process ProductAdded event: {e}")
            raise


# --8<-- [end:projector]
