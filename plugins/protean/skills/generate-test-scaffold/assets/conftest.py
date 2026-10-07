"""
conftest.py for running the scaffold modules exactly as written.

Put it in a folder of its own, next to the scaffold modules. Every test module
in that folder must define `domain`, because the fixture reads it from there.
It is not a project's root conftest: a project test module that does not define
`domain` would fail. A project uses the conftest in SKILL.md Step 7.

This example demonstrates:
- DomainFixture from protean.integrations.pytest, which initializes the domain,
  creates the database schema, and drops it at the end
- Test mode: event and command processing set to "sync" before setup(), so a
  test sees handler side effects as soon as it persists or processes
- A per-test domain context that resets every provider, broker, and event store
  after each test

Each scaffold module here defines its own domain, so the fixture reads `domain`
from the test module and is module-scoped. The SKILL.md Step 7 conftest imports
the project's one domain and is session-scoped instead:

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
