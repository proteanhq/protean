# --8<-- [start:full]
import os

from protean import Domain
from protean.fields import String

domain = Domain(name="Accounts")
domain.config["databases"]["default"] = {
    "provider": "mssql",
    "database_uri": os.environ.get(
        "MSSQL_URL",
        "mssql+pyodbc://sa:Protean123!@localhost:1433/master"
        "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes",
    ),
}


# --8<-- [start:key_columns]
@domain.aggregate
class User:
    email: String(max_length=255, unique=True)  # length is required here
    bio: String(max_length=None)  # fine, not a key column


@domain.aggregate
class Coupon:
    code: String(max_length=None, unique=True)  # raises: a key column with no length


# --8<-- [end:key_columns]


domain.init(traverse=False)
# --8<-- [end:full]
