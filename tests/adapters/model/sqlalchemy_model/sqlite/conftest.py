import os

import pytest


def initialize_domain():
    from protean.domain import Domain

    domain = Domain(__file__, "SQLAlchemy Test - SQLite")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    return domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain()
    domain.reinitialize()

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="session", autouse=True)
def setup_db():
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
        domain.register_model(ProviderCustomModel, entity_cls=Provider)

        domain.repository_for(ArrayUser)._dao
        domain.repository_for(ComplexUser)._dao
        domain.repository_for(Event)._dao
        domain.repository_for(IntegerArrayUser)._dao
        domain.repository_for(Person)._dao
        domain.repository_for(Provider)._dao
        domain.repository_for(User)._dao

        domain.providers["default"]._metadata.create_all()

        yield

        # Drop all tables at the end of test suite
        domain.providers["default"]._metadata.drop_all()
