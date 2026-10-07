# --8<-- [start:full]
from protean import Domain
from protean.fields import String

domain = Domain()
domain.config["databases"] = {
    "default": {
        "provider": "sqlite",
        "database_uri": "sqlite:///test.db",
    },
    "archive": {
        "provider": "sqlite",
        "database_uri": "sqlite:///archive.db",
    },
}


@domain.aggregate(provider="archive")
class User:
    name: String(max_length=30)
    email: String(required=True)
    timezone: String(max_length=30)


# --8<-- [end:full]
