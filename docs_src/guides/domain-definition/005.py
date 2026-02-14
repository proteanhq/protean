import sqlalchemy

from protean import Domain
from protean.fields import String

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
    first_name: String(max_length=30)
    last_name: String(max_length=30)


@domain.database_model(entity_cls=Person)
class PersonModel:
    first_name = sqlalchemy.Column(sqlalchemy.Text)
    last_name = sqlalchemy.Column(sqlalchemy.Text)
