import sqlalchemy

from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()
domain.config["DATABASES"] = {
    "default": {
        "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
        "DATABASE": "SQLITE",
        "DATABASE_URI": "sqlite:///test.db",
    }
}


@domain.aggregate
class Person:
    first_name: Annotated[str, Field(max_length=30)] | None = None
    last_name: Annotated[str, Field(max_length=30)] | None = None


@domain.database_model(part_of=Person)
class PersonModel:
    first_name = sqlalchemy.Column(sqlalchemy.Text)
    last_name = sqlalchemy.Column(sqlalchemy.Text)
