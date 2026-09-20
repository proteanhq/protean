"""
Multi-step upcaster chain for events evolving through multiple versions.

This example demonstrates:
- An event evolving through 4 versions (v1 -> v2 -> v3 -> v4)
- Automatic chain building by the framework
- Full chain application (v1 passes through v1->v2->v3->v4)
- Partial chain application (v2 passes through v2->v3->v4 only)
- Zero overhead for current-version events (v4 bypasses chain entirely)

Domain: Product catalog
    - ProductPriceChanged event evolves through 4 versions
    - v1: product_id, price
    - v2: product_id, price, currency (added currency)
    - v3: product_id, new_price, currency (renamed price -> new_price)
    - v4: product_id, new_price, currency, discount_pct (added discount_pct)

Usage:
    from upcaster_multi_step_chain import domain, ProductPriceChanged

    domain.init(traverse=False)
    with domain.domain_context():
        chain = domain._upcaster_chain
        # v1 data passes through full chain
        result = chain.upcast("UpcasterMultiStepChain.ProductPriceChanged", 1,
                              {"product_id": "P-1", "price": 29.99})
"""

from protean import Domain
from protean.core.aggregate import apply
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()


# --- Event (current version: v4) ---


@domain.event(part_of="Product")
class ProductPriceChanged:
    """Product price was updated. Current version: v4.

    Evolution history:
        v1: product_id, price
        v2: product_id, price, currency (added)
        v3: product_id, new_price, currency (renamed price -> new_price)
        v4: product_id, new_price, currency, discount_pct (added)
    """

    __version__ = 4

    product_id = Identifier(required=True)
    new_price = Float(required=True)
    currency = String(required=True)
    discount_pct = Float(required=True)


# --- Upcaster chain: v1 -> v2 -> v3 -> v4 ---


@domain.upcaster(event_type=ProductPriceChanged, from_version=1, to_version=2)
class UpcastPriceChangedV1ToV2(BaseUpcaster):
    """v1 -> v2: Add currency field with default USD."""

    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


@domain.upcaster(event_type=ProductPriceChanged, from_version=2, to_version=3)
class UpcastPriceChangedV2ToV3(BaseUpcaster):
    """v2 -> v3: Rename 'price' to 'new_price'."""

    def upcast(self, data: dict) -> dict:
        data["new_price"] = data.pop("price")
        return data


@domain.upcaster(event_type=ProductPriceChanged, from_version=3, to_version=4)
class UpcastPriceChangedV3ToV4(BaseUpcaster):
    """v3 -> v4: Add discount_pct with default 0.0."""

    def upcast(self, data: dict) -> dict:
        data["discount_pct"] = 0.0
        return data


# --- Aggregate ---


@domain.aggregate(is_event_sourced=True)
class Product:
    """Event-sourced product aggregate."""

    product_id = Identifier(identifier=True)
    name = String(required=True, max_length=200)
    price = Float(default=0.0)
    currency = String(default="USD")
    discount_pct = Float(default=0.0)

    @classmethod
    def create(cls, product_id, name, price, currency="USD"):
        """Factory: create a new product."""
        return cls(product_id=product_id, name=name, price=price, currency=currency)

    def change_price(self, new_price, currency=None, discount_pct=0.0):
        """Change the product's price."""
        if new_price < 0:
            raise ValueError("Price cannot be negative")
        self.raise_(
            ProductPriceChanged(
                product_id=self.product_id,
                new_price=new_price,
                currency=currency or self.currency,
                discount_pct=discount_pct,
            )
        )

    @apply
    def on_price_changed(self, event: ProductPriceChanged):
        self.price = event.new_price
        self.currency = event.currency
        self.discount_pct = event.discount_pct


# Example usage
if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)

    with domain.domain_context():
        chain = domain._upcaster_chain

        # Determine the base type string
        base_type = ProductPriceChanged.__type__.rpartition(".")[0]
        print(f"Event base type: {base_type}")

        # v1 data passes through full chain (v1 -> v2 -> v3 -> v4)
        v1_data = {"product_id": "P-1", "price": 29.99}
        result = chain.upcast(base_type, 1, dict(v1_data))
        print(f"v1 -> v4: {result}")
        # Expected: new_price=29.99, currency=USD, discount_pct=0.0

        # v2 data passes through partial chain (v2 -> v3 -> v4)
        v2_data = {"product_id": "P-1", "price": 29.99, "currency": "EUR"}
        result = chain.upcast(base_type, 2, dict(v2_data))
        print(f"v2 -> v4: {result}")
        # Expected: new_price=29.99, currency=EUR, discount_pct=0.0

        # v3 data passes through single step (v3 -> v4)
        v3_data = {"product_id": "P-1", "new_price": 39.99, "currency": "GBP"}
        result = chain.upcast(base_type, 3, dict(v3_data))
        print(f"v3 -> v4: {result}")
        # Expected: new_price=39.99, currency=GBP, discount_pct=0.0

        # v4 data passes through unchanged (no chain for current version)
        v4_data = {
            "product_id": "P-1",
            "new_price": 49.99,
            "currency": "JPY",
            "discount_pct": 10.0,
        }
        result = chain.upcast(base_type, 4, dict(v4_data))
        print(f"v4 (current): {result}")
        # Expected: unchanged
