"""A user model declared with ``@domain.database_model`` stores and loads an
aggregate on Elasticsearch."""

import pytest
from elasticsearch.dsl import Keyword, Text

from protean.adapters.repository.elasticsearch import ElasticsearchModel
from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.fields import String


class Author(BaseAggregate):
    name: String(max_length=50)
    about: String(max_length=200)


class AuthorModel(BaseDatabaseModel):
    id = Keyword()
    name = Text(fields={"raw": Keyword()})
    about = Text()


@pytest.mark.elasticsearch
def test_a_user_declared_model_round_trips_an_aggregate(test_domain):
    test_domain.register(Author)
    test_domain.register_database_model(
        AuthorModel, part_of=Author, schema_name="user_declared_authors"
    )
    test_domain.init(traverse=False)

    provider = test_domain.providers["default"]
    provider.create_schema()
    try:
        model_cls = test_domain.repository_for(Author)._database_model
        assert issubclass(model_cls, ElasticsearchModel)
        assert issubclass(model_cls, AuthorModel)

        author = Author(name="Jane", about="Writes novels")
        test_domain.repository_for(Author).add(author)

        restored = test_domain.repository_for(Author).get(author.id)
        assert restored.id == author.id
        assert restored.name == "Jane"
        assert restored.about == "Writes novels"
    finally:
        provider.drop_schema()
