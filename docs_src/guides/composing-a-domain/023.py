from protean import Domain
from protean.fields import Auto, String

domain = Domain()


@domain.aggregate
class User:
    user_id = Auto(identifier=True)
    name = String(required=True)
