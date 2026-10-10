# The page shows this import above the aggregate, so it sits at the top here.
# --8<-- [start:import]
from protean.core.database_model import BaseDatabaseModel

# --8<-- [end:import]
# isort: split
from protean import Domain
from protean.fields import Float, String, Text

domain = Domain()


# --8<-- [start:custom_model]
@domain.aggregate
class Product:
    name = String(required=True)
    description = Text()
    price = Float()


class ProductModel(BaseDatabaseModel):
    pass  # Empty -- just override the schema name


domain.register(ProductModel, part_of=Product, schema_name="products")
# --8<-- [end:custom_model]


# --8<-- [start:options]
class ProductReportingModel(BaseDatabaseModel):
    pass


domain.register(
    ProductReportingModel,
    part_of=Product,
    schema_name="product_reports",
    database="postgresql",
)
# --8<-- [end:options]

if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        model_cls = domain.repository_for(Product)._dao.database_model_cls
        product = Product(name="Pen", description="A blue pen", price=1.5)
        print(model_cls.to_entity(model_cls.from_entity(product)) == product)
