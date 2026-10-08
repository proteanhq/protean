from protean import Domain
from protean.fields import Auto, String

domain = Domain(name="CreatingIdentitiesEarlyInvoices")


# --8<-- [start:sequence]
@domain.aggregate
class Invoice:
    invoice_number: Auto(identifier=True, increment=True)
    # ...
    # --8<-- [end:sequence]
    customer_name: String(max_length=100)
