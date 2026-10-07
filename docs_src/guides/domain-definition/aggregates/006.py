from protean import Domain
from protean.fields import Float

domain = Domain(name="Billing")


# --8<-- [start:aggregate]
@domain.aggregate
class Invoice:
    subtotal: Float(required=True)
    tax_rate: Float(default=0.1)
    total: Float()

    def defaults(self):
        if self.total is None:
            self.total = self.subtotal * (1 + self.tax_rate)


# --8<-- [end:aggregate]
