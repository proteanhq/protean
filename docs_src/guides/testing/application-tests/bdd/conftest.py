# --8<-- [start:shared_steps]
# tests/bdd/conftest.py
from pytest_bdd import given


@given("the domain is initialized")
def domain_initialized():
    """The root conftest has already initialized the domain."""


# --8<-- [end:shared_steps]


# --8<-- [start:markers]
def pytest_configure(config):
    for tag in ("ordering", "smoke", "happy_path", "validation"):
        config.addinivalue_line("markers", f"{tag}: Gherkin tag")


# --8<-- [end:markers]
