import sqlalchemy as sa

from protean import Domain
from protean.adapters.repository.sqlalchemy import SqlalchemyModel
from protean.fields import Integer, String

domain = Domain()
domain.config["databases"]["default"] = {
    "provider": "postgresql",
    "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
}


@domain.aggregate
class Provider:
    name = String()
    age = Integer()


@domain.database_model(part_of=Provider)
class ProviderCustomModel:
    name = sa.Column(sa.Text)
    age = sa.Column(sa.Integer)


domain.init()
with domain.domain_context():
    database_model_cls = domain.repository_for(Provider)._database_model
    assert issubclass(database_model_cls, SqlalchemyModel)
