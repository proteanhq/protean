# --8<-- [start:full]
import os

import sqlalchemy as sa
from sqlalchemy.dialects import mssql

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


@domain.aggregate
class User:
    name: String(max_length=100)
    email: String(max_length=255)


@domain.database_model(part_of=User)
class UserModel:
    name = sa.Column(mssql.NVARCHAR(100))
    email = sa.Column(mssql.NVARCHAR(255), unique=True)


domain.init(traverse=False)
# --8<-- [end:full]
