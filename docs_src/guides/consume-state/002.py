from uuid import uuid4

from protean import Domain, handle, invariant
from protean.fields import Float, Identifier, Integer, String, Text

domain = Domain("__file__")

# Process events and commands synchronously
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


@domain.aggregate
class Product:
    name = String(max_length=100, required=True)
    description = Text()
    price = Float(required=True)
    stock_quantity = Integer(default=0)

    @invariant.post
    def quantity_must_be_positive(self):
        if self.stock_quantity < 0:
            raise ValueError("Stock quantity must be positive")

    def adjust_stock(self, quantity):
        self.stock_quantity += quantity

        self.raise_(
            StockAdjusted(
                product_id=self.id,
                quantity=quantity,
                new_stock_quantity=self.stock_quantity,
            )
        )


@domain.command(part_of=Product)
class AddProduct:
    product_id = Identifier(required=True)
    name = String(max_length=100, required=True)
    description = Text(required=True)
    price = Float(required=True)
    stock_quantity = Integer(default=0)


@domain.command(part_of=Product)
class AdjustStock:
    product_id = Identifier(required=True)
    quantity = Integer(required=True)


@domain.event(part_of=Product)
class ProductAdded:
    product_id = Identifier(required=True)
    name = String(max_length=100, required=True)
    description = Text(required=True)
    price = Float(required=True)
    stock_quantity = Integer(default=0)


@domain.event(part_of=Product)
class StockAdjusted:
    product_id = Identifier(required=True)
    quantity = Integer(required=True)
    new_stock_quantity = Integer(required=True)


@domain.view
class ProductInventory:
    product_id = Identifier(identifier=True, required=True)
    name = String(max_length=100, required=True)
    description = Text(required=True)
    price = Float(required=True)
    stock_quantity = Integer(default=0)


@domain.command_handler(part_of=Product)
class ManageProducts:
    @handle(AddProduct)
    def add_product(self, command: AddProduct):
        repository = domain.repository_for(Product)

        product = Product(
            id=command.product_id,
            name=command.name,
            description=command.description,
            price=command.price,
            stock_quantity=command.stock_quantity,
        )

        product.raise_(
            ProductAdded(
                product_id=product.id,
                name=product.name,
                description=product.description,
                price=product.price,
                stock_quantity=product.stock_quantity,
            )
        )

        repository.add(product)

    @handle(AdjustStock)
    def adjust_stock(self, command: AdjustStock):
        repository = domain.repository_for(Product)
        product = repository.get(command.product_id)

        product.adjust_stock(command.quantity)

        repository.add(product)


@domain.event_handler(stream_category="product")
class SyncInventory:
    @handle(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        repository = domain.repository_for(ProductInventory)

        product = ProductInventory(
            product_id=event.product_id,
            name=event.name,
            description=event.description,
            price=event.price,
            stock_quantity=event.stock_quantity,
        )

        repository.add(product)

    @handle(StockAdjusted)
    def on_stock_adjusted(self, event: StockAdjusted):
        repository = domain.repository_for(ProductInventory)
        product = repository.get(event.product_id)

        product.stock_quantity = event.new_stock_quantity

        repository.add(product)


domain.init(traverse=False)
with domain.domain_context():
    # Add Product
    command = AddProduct(
        product_id=str(uuid4()),
        name="Apple",
        description="Fresh Apple",
        price=1.0,
        stock_quantity=100,
    )
    domain.process(command)

    # Confirm that Inventory View has the correct stock quantity
    repository = domain.repository_for(ProductInventory)
    inventory_record = repository.get(command.product_id)
    assert inventory_record.stock_quantity == 100

    # Adjust Stock
    adjust_command = AdjustStock(product_id=command.product_id, quantity=-50)
    domain.process(adjust_command)

    # Confirm that Inventory View has the correct stock quantity
    inventory_record = repository.get(command.product_id)
    assert inventory_record.stock_quantity == 50
