# --8<-- [start:full]
import os

from protean import Domain
from protean.fields import Integer, String

domain = Domain(name="Accounts")
domain.config["databases"]["default"] = {
    "provider": "postgresql",
    "database_uri": os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
    ),
}


@domain.aggregate(schema_name="users")
class User:
    name: String(max_length=50)
    age: Integer()


domain.init(traverse=False)
# --8<-- [end:full]


# --8<-- [start:raw]
def users_older_than(age):
    return domain.providers["default"].raw(
        "SELECT * FROM users WHERE age > :age", {"age": age}
    )


# --8<-- [end:raw]
