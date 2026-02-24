# --8<-- [start:full]
from protean import Domain

domain = Domain()

domain.config["databases"]["default"] = {
    "provider": "sqlalchemy",
    "database": "sqlite",
    "database_uri": "sqlite:///test.db",
}

domain.init(traverse=False)
# --8<-- [end:full]
