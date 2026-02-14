from protean import Domain
from protean.fields import String

domain = Domain()
domain.config["DATABASES"] = {
    "default": {
        "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
        "DATABASE": "SQLITE",
        "DATABASE_URI": "sqlite:///test.db",
    },
    "nosql": {
        "PROVIDER": "protean.adapters.repository.elasticsearch.ESProvider",
        "DATABASE": "ELASTICSEARCH",
        "DATABASE_URI": {"hosts": ["localhost"]},
    },
}


@domain.aggregate(provider="nosql")
class User:
    name: String(max_length=30)
    email: String(required=True)
    timezone: String(max_length=30)
