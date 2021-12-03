from protean import BaseEventSourcedAggregate
from protean.fields import Integer, String
from protean.fields.basic import Identifier


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach identifier
    name = String()
    age = Integer()


class AdminUser(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach identifier
    name = String()


class Person(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach identifier
    name = String()
    age = Integer()

    class Meta:
        stream_name = "people"


def test_stream_name_option_of_an_event_sourced_aggregate():
    assert User.meta_.stream_name == "user"

    # Verify snake-casing the Aggregate name
    assert AdminUser.meta_.stream_name == "admin_user"

    # Verify manually set stream_name
    assert Person.meta_.stream_name == "people"


def test_stream_name_option_of_an_event_sourced_aggregate_defined_via_annotation(
    test_domain,
):
    @test_domain.event_sourced_aggregate
    class Adult(BaseEventSourcedAggregate):
        id = Identifier(identifier=True)  # FIXME Auto-attach identifier
        name = String()
        age = Integer()

    assert Adult.meta_.stream_name == "adult"

    @test_domain.event_sourced_aggregate(stream_name="children")
    class Child(BaseEventSourcedAggregate):
        id = Identifier(identifier=True)  # FIXME Auto-attach identifier
        name = String()
        age = Integer()

    assert Child.meta_.stream_name == "children"
