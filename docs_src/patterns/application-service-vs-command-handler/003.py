from protean import Domain

domain = Domain(name="ApplicationServiceProducts")

# --8<-- [start:product_service]
from protean import current_domain
from protean.core.application_service import BaseApplicationService, use_case
from protean.fields import Auto, Float, String


@domain.aggregate
class Product:
    product_id: Auto(identifier=True)
    name: String(required=True, max_length=100)
    price: Float(required=True)


@domain.application_service(part_of=Product)
class ProductService(BaseApplicationService):
    @use_case
    def create_product(self, name: str, price: float) -> Product:
        repo = current_domain.repository_for(Product)
        product = Product(name=name, price=price)
        repo.add(product)
        return product


# --8<-- [end:product_service]

domain.init(traverse=False)
