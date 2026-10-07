# --8<-- [start:full]
import os

from protean import Domain, Index
from protean.fields import String

domain = Domain(name="Accounts")
domain.config["databases"]["default"] = {
    "provider": "mysql",
    "database_uri": os.environ.get(
        "MYSQL_URL", "mysql+pymysql://root:protean@localhost:3306/protean"
    ),
}


# --8<-- [start:key_columns]
@domain.aggregate
class User:
    email: String(max_length=255, unique=True)  # fine
    bio: String(max_length=4000)  # fine, not a key column
    token: String(max_length=1000, unique=True)  # raises: past the key limit


# --8<-- [end:key_columns]


# --8<-- [start:composite_index]
@domain.aggregate(indexes=[Index("tenant", "slug")])
class Document:
    tenant: String(max_length=500)  # 2000 bytes
    slug: String(max_length=500)  # 2000 bytes, and 4000 together: raises


# --8<-- [end:composite_index]
domain.init(traverse=False)
# --8<-- [end:full]
