# --8<-- [start:full]
import sqlalchemy as sa

from protean import Domain
from protean.fields import String

domain = Domain(name="Accounts")
domain.config["databases"]["default"] = {
    "provider": "sqlite",
    "database_uri": "sqlite:///test.db",
}


@domain.aggregate
class User:
    name: String(max_length=100)
    email: String(max_length=255)


@domain.database_model(part_of=User)
class UserModel:
    name = sa.Column(sa.String(100))
    email = sa.Column(sa.String(255), unique=True)


domain.init(traverse=False)
# --8<-- [end:full]
