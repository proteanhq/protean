import os

import pytest


def initialize_domain():
    from protean.domain import Domain

    domain = Domain("Elasticsearch Tests")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    return domain


@pytest.fixture
def test_domain():
    domain = initialize_domain()
    with domain.domain_context():
        yield domain


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    domain = initialize_domain()
    with domain.domain_context():
        # Create all indexes
        from .elements import (
            Alien,
            ComplexUser,
            Person,
            Provider,
            ProviderCustomModel,
            User,
        )

        domain.register(Person)
        domain.register(Alien)
        domain.register(User)
        domain.register(ComplexUser)
        domain.register(Provider)
        domain.register_model(ProviderCustomModel, entity_cls=Provider)

        domain.providers["default"]._create_database_artifacts()

        yield

        domain.providers["default"]._drop_database_artifacts()
