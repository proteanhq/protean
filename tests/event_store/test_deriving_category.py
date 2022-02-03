import pytest


@pytest.mark.eventstore
def test_deriving_category(test_domain):
    assert test_domain.event_store.store.category(None) == ""
    assert test_domain.event_store.store.category("") == ""

    assert (
        test_domain.event_store.store.category(
            "user-9702f3da-46c7-4415-b383-cb5f337cb4cd"
        )
        == "user"
    )
    assert test_domain.event_store.store.category("user") == "user"
    assert test_domain.event_store.store.category("user:command") == "user:command"
