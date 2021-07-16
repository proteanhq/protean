import os

import pytest


def initialize_domain():
    from protean.domain import Domain

    domain = Domain("Redis Cache Tests")

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
