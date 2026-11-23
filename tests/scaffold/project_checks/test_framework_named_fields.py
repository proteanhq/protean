"""A generated ``Thing`` slice whose fields take framework names (``id``,
``Text``, ``Identifier``) creates the aggregate and reads it back by the id its
authored ``id`` field holds.

Runs inside a project that ``protean new`` generates, after
``tests/scaffold/test_slice_generator.py`` writes the slice into it.
"""

from scaffolded.domain import scaffolded
from scaffolded.thing.aggregate import Thing
from scaffolded.thing.commands import CreateThing


def test_the_thing_is_read_back_by_its_authored_id() -> None:
    scaffolded.process(
        CreateThing(
            id="thing-1",
            name="a name",
            Text="a",
            note="b",
            Identifier="i",
            ref="r",
        )
    )

    found = scaffolded.repository_for(Thing).get("thing-1")

    assert (found.id, found.Text, found.note, found.Identifier, found.ref) == (
        "thing-1",
        "a",
        "b",
        "i",
        "r",
    )
