import pytest

from tests.shared import initialize_domain


@pytest.fixture
def test_domain():
    domain = initialize_domain(
        name="SQLAlchemy Postgres Repository Tests", root_path=__file__
    )

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    domain = initialize_domain(
        name="SQLAlchemy Postgres Repository DB Setup", root_path=__file__
    )
    with domain.domain_context():
        # Create all associated tables
        from .elements import Alien, ComplexUser, Person, User
        from .test_associations import Audit, Comment, Post
        from .test_persistence import Event
        from .test_persisting_list_of_value_objects import Customer, Order

        domain.register(Alien)
        domain.register(ComplexUser)
        domain.register(Event)
        domain.register(Person)
        domain.register(User)
        domain.register(Post)
        domain.register(Comment, part_of=Post)
        domain.register(Audit)
        domain.register(Order)
        domain.register(Customer, part_of=Order)
        domain.init(traverse=False)

        domain.repository_for(Alien)._dao
        domain.repository_for(ComplexUser)._dao
        domain.repository_for(Event)._dao
        domain.repository_for(Person)._dao
        domain.repository_for(User)._dao
        domain.repository_for(Post)._dao
        domain.repository_for(Comment)._dao
        domain.repository_for(Audit)._dao
        domain.repository_for(Customer)._dao
        domain.repository_for(Order)._dao

        default_provider = domain.providers["default"]
        default_provider._metadata.create_all(default_provider._engine)

        yield

        # Drop all tables at the end of test suite
        default_provider = domain.providers["default"]
        default_provider._metadata.drop_all(default_provider._engine)
