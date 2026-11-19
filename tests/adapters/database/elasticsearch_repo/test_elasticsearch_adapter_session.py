"""The Elasticsearch adapter DAO writes through the provider's client and
never touches the session it is given."""

import pytest

from protean import Q

from .elements import Person


class UntouchableSession:
    """A session that fails the test on any use, including a commit."""

    def __getattr__(self, name):
        raise AssertionError(f"the Elasticsearch adapter used session.{name}")


@pytest.mark.elasticsearch
def test_every_storage_operation_leaves_the_session_alone(test_domain):
    test_domain.register(Person)
    test_domain.init(traverse=False)
    adapter = test_domain.repository_for(Person)._dao._adapter
    adapter.delete_all(UntouchableSession(), Q())
    session = UntouchableSession()
    athos = adapter.database_model_cls.from_entity(
        Person(first_name="Athos", last_name="Musketeer", age=2)
    )
    porthos = adapter.database_model_cls.from_entity(
        Person(first_name="Porthos", last_name="Musketeer", age=3)
    )

    adapter.insert(session, athos)
    adapter.insert(session, porthos)
    athos.age = 4
    adapter.update(session, athos)
    assert adapter.update_all(session, Q(first_name="Porthos"), {"age": 5}) == 1
    assert adapter.count(session, Q(last_name="Musketeer")) == 2
    rows = adapter.filter(session, Q(last_name="Musketeer"), order_by=["age"])
    assert [(row.first_name, row.age) for row in rows.items] == [
        ("Athos", 4),
        ("Porthos", 5),
    ]
    adapter.delete(session, rows.items[0])
    assert adapter.delete_top(session, Q(first_name="Porthos"), limit=1) == 1
    assert adapter.delete_all(session, Q()) == 0
