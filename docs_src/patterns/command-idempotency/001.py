# --8<-- [start:config]
import os

from protean import Domain

domain = Domain(name="Carts")

# Without a Redis URL the idempotency store is off: Layers 1 and 2 do nothing.
domain.config["idempotency"]["redis_url"] = os.environ.get("REDIS_URL")
domain.config["idempotency"]["ttl"] = 86400
domain.config["idempotency"]["error_ttl"] = 60
# --8<-- [end:config]

from protean import handle
from protean.fields import Identifier, Integer, String
from protean.utils.globals import current_domain


@domain.aggregate
class Cart:
    cart_id: Identifier(identifier=True)
    product_id: String()
    quantity: Integer(default=0)


@domain.command(part_of=Cart)
class AddItemToCart:
    cart_id: Identifier(identifier=True)
    product_id: String(required=True)
    quantity: Integer(required=True)


@domain.command_handler(part_of=Cart)
class CartCommandHandler:
    @handle(AddItemToCart)
    def add_item(self, command: AddItemToCart) -> int:
        # Additive on purpose, with no guard of its own: only the
        # idempotency store stands between a retry and a doubled quantity.
        repo = current_domain.repository_for(Cart)
        cart = repo.get(command.cart_id)
        cart.product_id = command.product_id
        cart.quantity += command.quantity
        repo.add(cart)
        return cart.quantity
