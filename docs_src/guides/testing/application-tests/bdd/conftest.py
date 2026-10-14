# --8<-- [start:shared_steps]
# tests/bdd/conftest.py
from pytest_bdd import given


@given("the domain is initialized")
def domain_initialized():
    """The root conftest has already initialized the domain."""


# --8<-- [end:shared_steps]
