import pytest

from protean.infra.event_store import EventStore


@pytest.mark.eventstore
def test_deriving_category(test_domain):
    test_domain.init(traverse=False)

    assert EventStore.category(None) == ""
    assert EventStore.category("") == ""

    assert EventStore.category("user-9702f3da-46c7-4415-b383-cb5f337cb4cd") == "user"
    assert EventStore.category("user") == "user"
    assert EventStore.category("user:command") == "user:command"
