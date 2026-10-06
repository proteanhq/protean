"""
Root conftest.py for the scaffold test modules.

This example demonstrates:
- DomainFixture from protean.integrations.pytest, which initializes the domain,
  creates the database schema, and drops it at the end
- Test mode: event and command processing set to "sync" before setup(), so a
  test sees handler side effects as soon as it persists or processes
- A per-test domain context that resets every provider, broker, and event store
  after each test

Each scaffold module here defines its own domain, so the fixture reads `domain`
from the test module and is module-scoped. In a project with one domain, import
it and make the fixture session-scoped instead:

    from myapp import domain

    @pytest.fixture(scope="session")
    def app_fixture():
        domain.config["event_processing"] = "sync"
        ...

A bare `Domain()` processes events and commands asynchronously. A project made
by `protean new` sets both to "sync" in its domain.toml. The fixture sets them
here too, so a copied test passes either way.
"""

import pytest

from protean.integrations.pytest import DomainFixture


@pytest.fixture(scope="module")
def app_fixture(request):
    domain = request.module.domain
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield
