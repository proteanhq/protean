import pytest

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain(name="PostgreSQL Model Tests", root_path=__file__)

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    domain = initialize_domain(name="PostgreSQL Model DB Setup", root_path=__file__)
    with domain.domain_context():
        # Create all associated tables
        from .elements import (
            ComplexUser,
            IntegerListUser,
            ListUser,
            Person,
            Provider,
            ProviderCustomModel,
            User,
        )
        from .test_array_datatype import ArrayUser, IntegerArrayUser
        from .test_json_datatype import Event
        from .test_lookups import GenericPostgres

        domain.register(ArrayUser)
        domain.register(GenericPostgres)
        domain.register(ComplexUser)
        domain.register(Event)
        domain.register(IntegerArrayUser)
        domain.register(Person)
        domain.register(Provider)
        domain.register(User)
        domain.register(ListUser)
        domain.register(IntegerListUser)

        domain.register_database_model(
            ProviderCustomModel, part_of=Provider, schema_name="adults"
        )
        domain.init(traverse=False)

        domain.repository_for(ArrayUser)._dao
        domain.repository_for(GenericPostgres)._dao
        domain.repository_for(ComplexUser)._dao
        domain.repository_for(Event)._dao
        domain.repository_for(IntegerArrayUser)._dao
        domain.repository_for(Person)._dao
        domain.repository_for(Provider)._dao
        domain.repository_for(User)._dao
        domain.repository_for(ListUser)._dao
        domain.repository_for(IntegerListUser)._dao

        default_provider = domain.providers["default"]
        default_provider._metadata.create_all(default_provider._engine)

        yield

        # Drop all tables and dispose the engine to release connections
        default_provider = domain.providers["default"]
        default_provider._metadata.drop_all(default_provider._engine)
        default_provider.close()
