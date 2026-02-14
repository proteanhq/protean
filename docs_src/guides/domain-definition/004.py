from protean import Domain
from typing import Annotated
from pydantic import Field

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
    name: Annotated[str, Field(max_length=30)] | None = None
    email: str
    timezone: Annotated[str, Field(max_length=30)] | None = None
