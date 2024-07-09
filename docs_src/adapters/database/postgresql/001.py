import sqlalchemy as sa

from protean import Domain
from protean.adapters.repository.sqlalchemy import SqlalchemyModel
from protean.fields import Integer, String

domain = Domain(__file__, load_toml=False)
domain.config["databases"]["default"] = {
    "provider": "postgresql",
    "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
}


@domain.aggregate
class Provider:
    name = String()
    age = Integer()


@domain.model(part_of=Provider)
class ProviderCustomModel:
    name = sa.Column(sa.Text)
    age = sa.Column(sa.Integer)


domain.init()
with domain.domain_context():
    model_cls = domain.repository_for(Provider)._model
    assert issubclass(model_cls, SqlalchemyModel)
