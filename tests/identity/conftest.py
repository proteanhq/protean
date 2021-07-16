import os

import pytest


@pytest.fixture
def test_domain_with_string_identity():
    from protean.domain import Domain

    domain = Domain("Test")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config_string.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    with domain.domain_context():
        yield domain


@pytest.fixture
def test_domain_with_int_identity():
    from protean.domain import Domain

    domain = Domain("Test")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config_int.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    with domain.domain_context():
        yield domain


@pytest.fixture
def test_domain_with_uuid_identity():
    from protean.domain import Domain

    domain = Domain("Test")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config_uuid.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    with domain.domain_context():
        yield domain


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):

    yield

    if test_domain.providers.has_provider("default"):
        test_domain.get_provider("default")._data_reset()
