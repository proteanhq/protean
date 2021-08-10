import os

from typing import List

import pytest

from protean.core.field.basic import Integer


def initialize_domain():
    from protean.domain import Domain

    domain = Domain("SQLAlchemy Test - SQLite")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    return domain


domain = initialize_domain()


@pytest.fixture(autouse=True)
def test_domain():
    with domain.domain_context():
        yield domain


@pytest.fixture(scope="session", autouse=True)
def setup_db():
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

        domain.register_model(ProviderCustomModel, entity_cls=Provider)

        domain.get_dao(ArrayUser)
        domain.get_dao(GenericPostgres)
        domain.get_dao(ComplexUser)
        domain.get_dao(Event)
        domain.get_dao(IntegerArrayUser)
        domain.get_dao(Person)
        domain.get_dao(Provider)
        domain.get_dao(User)
        domain.get_dao(ListUser)
        domain.get_dao(IntegerListUser)

        for provider in domain.providers_list():
            provider._metadata.create_all()

        yield

        # Drop all tables at the end of test suite
        for provider in domain.providers_list():
            provider._metadata.drop_all()


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):
    yield
    if test_domain.providers.has_provider("default"):
        test_domain.get_provider("default")._data_reset()
