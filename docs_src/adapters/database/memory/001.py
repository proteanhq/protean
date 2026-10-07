# --8<-- [start:full]
from protean import Domain
from protean.fields import Integer, String

domain = Domain(name="MemoryRaw")


@domain.aggregate
class User:
    name: String(max_length=50, required=True)
    age: Integer(required=True)
    status: String(max_length=10, default="active")


domain.init(traverse=False)

with domain.domain_context():
    repo = domain.repository_for(User)
    repo.add(User(name="Ada", age=36))
    repo.add(User(name="Tim", age=17))
    repo.add(User(name="Lin", age=40, status="inactive"))

    results = domain.providers["default"].raw('{"age__gt": 21, "status": "active"}')
# --8<-- [end:full]
