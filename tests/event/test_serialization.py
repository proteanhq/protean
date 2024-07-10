from uuid import UUID, uuid4

import pytest

from tests.event.elements import Person, PersonAdded


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonAdded, part_of=Person)
    test_domain.init(traverse=False)


def test_that_message_has_unique_identifier():
    event = PersonAdded(id=uuid4(), first_name="John", last_name="Doe")

    assert hasattr(event, "id")
    try:
        UUID(str(event.id))
    except ValueError:
        pytest.fail("Event ID is not valid UUID")


@pytest.mark.skip(reason="Yet to implement")
def test_that_event_messages_have_the_right_type():
    pass


@pytest.mark.skip(reason="Yet to implement")
def test_event_payload_construction():
    pass


@pytest.mark.skip(reason="Yet to implement")
def test_stringified_message():
    pass


@pytest.mark.skip(reason="Yet to implement")
def test_reconstruction_of_event_from_message():
    pass


@pytest.mark.skip(reason="Yet to implement")
def test_that_dates_in_message_are_serialized_and_deserialized():
    pass
