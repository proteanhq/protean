# --8<-- [start:setup]
from protean import Domain
from protean.core.database_model import BaseDatabaseModel
from protean.fields import String

domain = Domain(name="Accounts")


@domain.aggregate
class User:
    email: String(max_length=255, required=True)
    full_name: String(max_length=100)


# --8<-- [end:setup]


# --8<-- [start:fix]
@domain.database_model(part_of=User, schema_name="users")
class UserModel(BaseDatabaseModel):
    pass


# --8<-- [end:fix]
