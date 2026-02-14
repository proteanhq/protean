from protean import Domain
from protean.fields import Integer, String

domain = Domain()


@domain.aggregate
class User:
    first_name: String(max_length=50)
    last_name: String(max_length=50)
    age: Integer()
