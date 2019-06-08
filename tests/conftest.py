"""Module to setup Factories and other required artifacts for tests

    isort:skip_file
"""
import os

import pytest



def pytest_addoption(parser):
    """Additional options for running tests with pytest"""
    parser.addoption(
        "--slow", action="store_true", default=False, help="run slow tests"
    )
    parser.addoption(
        "--pending", action="store_true", default=False, help="show pending tests"
    )


def pytest_collection_modifyitems(config, items):
    """Configure special markers on tests, so as to control execution"""
    run_slow = run_pending = False

    if config.getoption("--slow"):
        # --slow given in cli: do not skip slow tests
        run_slow = True

    if config.getoption("--pending"):
        run_pending = True

    skip_slow = pytest.mark.skip(reason="need --slow option to run")
    skip_pending = pytest.mark.skip(reason="need --pending option to run")

    for item in items:
        if "slow" in item.keywords and run_slow is False:
            item.add_marker(skip_slow)
        if "pending" in item.keywords and run_pending is False:
            item.add_marker(skip_pending)


@pytest.fixture(autouse=True)
def test_domain():
    from protean.domain import Domain
    domain = Domain('Test')

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    with domain.domain_context():
        yield domain


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):

    yield

    if test_domain.has_provider('default'):
        test_domain.get_provider('default')._data_reset()
