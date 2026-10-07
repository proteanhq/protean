# --8<-- [start:full]
import os

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from protean import Domain
from protean.fields import Dict, String

domain = Domain(name="Preferences")
domain.config["databases"]["default"] = {
    "provider": "mysql",
    "database_uri": os.environ.get(
        "MYSQL_URL", "mysql+pymysql://root:protean@localhost:3306/protean"
    ),
}


@domain.aggregate
class User:
    name: String(max_length=100)
    preferences: Dict()


@domain.database_model(part_of=User)
class UserModel:
    name = sa.Column(mysql.VARCHAR(100))
    preferences = sa.Column(mysql.JSON)


domain.init(traverse=False)
# --8<-- [end:full]
