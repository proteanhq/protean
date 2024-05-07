from protean import Domain
from protean.fields import Float, String

domain = Domain(__name__)


@domain.value_object
class Balance:
    currency = String(max_length=3, required=True)
    amount = Float(required=True)
