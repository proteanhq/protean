# --8<-- [start:aggregate]
import uuid

from protean import Domain
from protean.fields import Auto, String

domain = Domain(name="Billing")


def invoice_number() -> str:
    return f"INV-{uuid.uuid4().hex[:12].upper()}"


@domain.aggregate
class Invoice:
    invoice_number: Auto(
        identifier=True,
        identity_strategy="function",
        identity_function=invoice_number,
        identity_type="string",
    )
    customer_name: String(max_length=100, required=True)


# --8<-- [end:aggregate]
