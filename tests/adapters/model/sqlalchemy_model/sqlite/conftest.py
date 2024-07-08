import pytest

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain(__file__, "SQLAlchemy Model Tests")

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    domain = initialize_domain(__file__, "SQLAlchemy Model DB Setup")
    with domain.domain_context():
        # Create all associated tables
        from .elements import ComplexUser, Person, Provider, ProviderCustomModel, User
        from .test_array_datatype import ArrayUser, IntegerArrayUser
        from .test_json_datatype import Event

        domain.register(ArrayUser)
        domain.register(ComplexUser)
        domain.register(Event)
        domain.register(IntegerArrayUser)
        domain.register(Person)
        domain.register(Provider)
        domain.register(User)
        domain.register_model(
            ProviderCustomModel, part_of=Provider, schema_name="adults"
        )
        domain.init(traverse=False)

        domain.repository_for(ArrayUser)._dao
        domain.repository_for(ComplexUser)._dao
        domain.repository_for(Event)._dao
        domain.repository_for(IntegerArrayUser)._dao
        domain.repository_for(Person)._dao
        domain.repository_for(Provider)._dao
        domain.repository_for(User)._dao

        default_provider = domain.providers["default"]
        default_provider._metadata.create_all(default_provider._engine)

        yield

        # Drop all tables at the end of test suite
        default_provider = domain.providers["default"]
        default_provider._metadata.drop_all(default_provider._engine)
