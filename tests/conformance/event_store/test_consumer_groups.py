"""Consumer groups split a category's streams between the group's members."""

import pytest

from protean.port.event_store import EventStoreCapabilities

pytestmark = pytest.mark.requires(EventStoreCapabilities.CONSUMER_GROUPS)


def _ids(rows) -> set[str]:
    return {row["id"] for row in rows}


def test_two_members_split_the_category_into_disjoint_sets(adapter):
    for n in range(8):
        adapter.write_message(f"user-{n}", "Counted", {"n": n})
        adapter.write_message(f"user-{n}", "Counted", {"n": n})

    member_0 = adapter.get_category_messages(
        "user", consumer_group_member=0, consumer_group_size=2
    )
    member_1 = adapter.get_category_messages(
        "user", consumer_group_member=1, consumer_group_size=2
    )

    every_row = _ids(adapter.get_category_messages("user"))
    assert len(every_row) == 16
    assert _ids(member_0).isdisjoint(_ids(member_1))
    assert _ids(member_0) | _ids(member_1) == every_row


def test_each_stream_goes_to_one_member(adapter):
    for n in range(8):
        adapter.write_message(f"user-{n}", "Counted", {"n": n})
        adapter.write_message(f"user-{n}", "Counted", {"n": n})

    member_0 = adapter.get_category_messages(
        "user", consumer_group_member=0, consumer_group_size=2
    )
    member_1 = adapter.get_category_messages(
        "user", consumer_group_member=1, consumer_group_size=2
    )

    streams_0 = {row["stream_name"] for row in member_0}
    streams_1 = {row["stream_name"] for row in member_1}
    assert streams_0.isdisjoint(streams_1)
    assert len(streams_0 | streams_1) == 8


@pytest.mark.parametrize(
    "group",
    [{"consumer_group_member": 0}, {"consumer_group_size": 2}],
    ids=["member-only", "size-only"],
)
def test_a_lone_group_argument_raises_value_error(adapter, group):
    with pytest.raises(ValueError):
        adapter.get_category_messages("user", **group)
