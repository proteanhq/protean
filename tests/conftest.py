"""Module to setup Factories and other required artifacts for tests"""
import os

import pytest

os.environ['PROTEAN_CONFIG'] = 'tests.support.sample_config'


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


@pytest.fixture(scope="session", autouse=True)
def test_domain():
    """Test Domain"""
    from protean.domain import Domain
    return Domain("Test")


@pytest.fixture(scope="session", autouse=True)
def register_domain_elements(test_domain):
    """Register Domain Elements with Stub Infrastructure, like:
    * Models with Dict Repo

    Run only once for the entire test suite
    """
    test_domain.register_elements()


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):
    """Cleanup Database after each test run"""
    # A test function will be run at this point
    yield

    # Reset Test Data
    from protean.core.provider import providers
    providers.get_provider()._data_reset()
