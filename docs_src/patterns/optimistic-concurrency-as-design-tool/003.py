from protean import Domain, UnitOfWork, current_domain
from protean.exceptions import ExpectedVersionError, ValidationError
from protean.fields import Auto, HasMany, Identifier, Integer

domain = Domain(name="OptimisticConcurrencySharedCart")

MAX_RETRIES = 3


# --8<-- [start:aggregate]
@domain.entity(part_of="SharedCart")
class CartItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True, min_value=1)


@domain.aggregate
class SharedCart:
    cart_id: Auto(identifier=True)
    team_id: Identifier(required=True)
    items = HasMany(CartItem)
    max_items: Integer(default=50)

    def add_item(self, product_id: str, quantity: int) -> None:
        """Add an item to the shared cart."""
        if len(self.items) >= self.max_items:
            raise ValidationError(
                {"items": [f"Cart cannot exceed {self.max_items} items"]}
            )

        # Check if item already exists and update quantity
        for item in self.items:
            if item.product_id == product_id:
                item.quantity += quantity
                self.raise_(
                    CartItemUpdated(
                        cart_id=self.cart_id,
                        product_id=product_id,
                        new_quantity=item.quantity,
                    )
                )
                return

        self.add_items(
            CartItem(
                product_id=product_id,
                quantity=quantity,
            )
        )
        self.raise_(
            CartItemAdded(
                cart_id=self.cart_id,
                product_id=product_id,
                quantity=quantity,
            )
        )


# --8<-- [end:aggregate]


@domain.event(part_of=SharedCart)
class CartItemAdded:
    cart_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.event(part_of=SharedCart)
class CartItemUpdated:
    cart_id: Identifier(required=True)
    product_id: Identifier(required=True)
    new_quantity: Integer(required=True)


# --8<-- [start:service]
@domain.application_service(part_of=SharedCart)
class SharedCartService:
    def add_item(self, cart_id: str, product_id: str, quantity: int) -> SharedCart:
        for attempt in range(MAX_RETRIES):
            try:
                # Each attempt loads the latest version in a fresh
                # transaction. The conflict surfaces when it commits.
                with UnitOfWork():
                    repo = current_domain.repository_for(SharedCart)
                    cart = repo.get(cart_id)

                    # Check if the operation still makes sense
                    # on the latest version
                    if len(cart.items) >= cart.max_items:
                        raise ValidationError(
                            {"items": ["Cart is full. Remove items first."]}
                        )

                    cart.add_item(product_id, quantity)
                    repo.add(cart)
                return cart
            except ExpectedVersionError:
                if attempt == MAX_RETRIES - 1:
                    raise
                # Reload and re-evaluate on the next attempt


# --8<-- [end:service]
