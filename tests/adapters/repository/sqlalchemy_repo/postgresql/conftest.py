import pytest

from tests.shared import initialize_domain


@pytest.fixture
def test_domain():
    domain = initialize_domain(__file__, "SQLAlchemy Postgres Repository Tests")

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    domain = initialize_domain(__file__, "SQLAlchemy Postgres Repository DB Setup")
    with domain.domain_context():
        # Create all associated tables
        from .elements import Alien, ComplexUser, Person, User
        from .test_associations import Audit, Comment, Post
        from .test_persistence import Event

        domain.register(Alien)
        domain.register(ComplexUser)
        domain.register(Event)
        domain.register(Person)
        domain.register(User)
        domain.register(Post)
        domain.register(Comment)
        domain.register(Audit)

        domain.repository_for(Alien)._dao
        domain.repository_for(ComplexUser)._dao
        domain.repository_for(Event)._dao
        domain.repository_for(Person)._dao
        domain.repository_for(User)._dao
        domain.repository_for(Post)._dao
        domain.repository_for(Comment)._dao
        domain.repository_for(Audit)._dao

        domain.providers["default"]._metadata.create_all()

        yield

        # Drop all tables at the end of test suite
        domain.providers["default"]._metadata.drop_all()
