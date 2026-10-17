# --8<-- [start:add_item]
from protean import Domain, handle
from protean.fields import Identifier, Integer, List, String
from protean.utils.globals import current_domain

domain = Domain(name="Carts")


@domain.aggregate
class Cart:
    cart_id: Identifier(identifier=True)
    product_id: String()
    quantity: Integer(default=0)
    processed_commands: List(content_type=String)

    def add_item(self, product_id: str, quantity: int) -> None:
        self.product_id = product_id
        self.quantity += quantity


@domain.command(part_of=Cart)
class AddItemToCart:
    cart_id: Identifier(identifier=True)
    product_id: String(required=True)
    quantity: Integer(required=True)


@domain.command_handler(part_of=Cart)
class CartCommandHandler:
    @handle(AddItemToCart)
    def add_item(self, command: AddItemToCart) -> None:
        repo = current_domain.repository_for(Cart)
        cart = repo.get(command.cart_id)

        # Check the command's idempotency key (if present) against
        # a set of recently processed keys stored on the aggregate
        idempotency_key = command._metadata.headers.idempotency_key
        if idempotency_key and idempotency_key in cart.processed_commands:
            return  # Already processed

        cart.add_item(command.product_id, command.quantity)

        if idempotency_key:
            cart.processed_commands.append(idempotency_key)

        repo.add(cart)


# --8<-- [end:add_item]
