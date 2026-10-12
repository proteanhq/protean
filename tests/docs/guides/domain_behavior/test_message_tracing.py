"""The examples on the message tracing guide behave as the page says."""

from types import SimpleNamespace

import pytest

from protean.server import Engine
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

CHAIN = [
    "MyApp.PlaceOrder.v1",
    "MyApp.OrderPlaced.v1",
    "MyApp.ReserveInventory.v1",
    "MyApp.InventoryReserved.v1",
]


@pytest.fixture
def tracing():
    example = load_example("guides/domain-behavior/message-tracing/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def _place_and_run(example, correlation_id):
    request = SimpleNamespace(headers={"X-Correlation-ID": correlation_id})
    example.place_order(request, [{"sku": "BOOK-1", "qty": 2}])
    Engine(example.domain, test_mode=True).run()
    messages = [
        message
        for message in example.domain.event_store.store.read("$all")
        if message.metadata.domain.correlation_id == correlation_id
    ]
    assert [message.metadata.headers.type for message in messages] == CHAIN
    return messages


def test_each_message_names_its_direct_parent(tracing):
    messages = _place_and_run(tracing, "ext-1")

    causes = [message.metadata.domain.causation_id for message in messages]
    ids = [message.metadata.headers.id for message in messages]
    assert causes == [None, ids[0], ids[1], ids[2]]


def test_trace_ids_reads_both_ids_from_an_object_and_a_message(tracing):
    command, placed, *_ = _place_and_run(tracing, "ext-1")

    object_ids, message_ids = tracing.trace_ids(command.to_domain_object(), placed)

    assert object_ids == ("ext-1", None)
    assert message_ids == ("ext-1", command.metadata.headers.id)


def test_trace_causation_walks_up_to_the_root(tracing, capsys):
    messages = _place_and_run(tracing, "ext-1")
    target = messages[-1]

    chain = tracing.show_causation(target.metadata.headers.id, target)

    assert [message.metadata.headers.type for message in chain] == CHAIN
    causes = [None] + [message.metadata.headers.id for message in messages[:-1]]
    assert capsys.readouterr().out.splitlines() == [
        f"{kind} (caused by {cause})"
        for kind, cause in zip(CHAIN, causes, strict=False)
    ]


def test_trace_effects_walks_down_from_the_command(tracing):
    command = _place_and_run(tracing, "ext-1")[0]

    effects, direct = tracing.show_effects(
        tracing.domain.event_store.store, command.metadata.headers.id
    )

    assert [message.metadata.headers.type for message in effects] == CHAIN[1:]
    assert [message.metadata.headers.type for message in direct] == CHAIN[1:2]


def test_the_causation_tree_starts_at_the_command(tracing, capsys):
    _place_and_run(tracing, "ext-1")

    tracing.show_tree(tracing.domain.event_store.store, "ext-1")

    assert capsys.readouterr().out.splitlines() == [
        "COMMAND MyApp.PlaceOrder.v1",
        "  EVENT MyApp.OrderPlaced.v1",
    ]


def test_an_unknown_correlation_id_prints_no_tree(tracing, capsys):
    tracing.show_tree(tracing.domain.event_store.store, "nothing-here")

    assert capsys.readouterr().out == ""


def test_the_dsl_groups_both_commands_under_one_correlation_id(tracing):
    result = tracing.place_and_reserve()

    assert result.aggregate.status == "RESERVED"
    assert result.aggregate.items == [{"sku": "BOOK-1", "qty": 2}]
    stored = list(tracing.domain.event_store.store.read("$all"))
    assert [message.metadata.headers.type for message in stored] == CHAIN
    assert {message.metadata.domain.correlation_id for message in stored} == {
        "checkout-42"
    }
    reserve = stored[CHAIN.index("MyApp.ReserveInventory.v1")]
    assert reserve.metadata.domain.causation_id is None


def test_outbox_rows_can_be_found_by_correlation_and_causation():
    example = load_example("guides/domain-behavior/message-tracing/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        example.domain.process(
            example.PlaceOrder(customer_id="cust-1"),
            asynchronous=False,
            correlation_id="ext-9",
        )
        command = example.domain.event_store.store.read_last_message(
            f"{example.Order.meta_.stream_category}:command"
        )
        by_correlation, by_causation = example.find_outbox_records(
            "ext-9", command.metadata.headers.id
        )
        unknown = example.find_outbox_records("nope", "nope")

    assert [row.type for row in by_correlation] == ["MyApp.OrderPlaced.v1"]
    assert [row.id for row in by_causation] == [row.id for row in by_correlation]
    assert by_correlation[0].correlation_id == "ext-9"
    assert unknown == ([], [])


def test_a_command_sent_from_a_sync_event_handler_names_the_original_command():
    example = load_example("guides/domain-behavior/message-tracing/001.py")
    example.domain.config["event_processing"] = "sync"
    example.domain.config["command_processing"] = "sync"
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        example.domain.process(
            example.PlaceOrder(customer_id="cust-1", items=[]),
            correlation_id="sync-1",
        )
        messages = [
            message
            for message in example.domain.event_store.store.read("$all")
            if message.metadata.domain.correlation_id == "sync-1"
        ]

    assert [message.metadata.headers.type for message in messages] == CHAIN
    place, placed, reserve, _ = messages
    assert reserve.metadata.domain.causation_id == place.metadata.headers.id
    assert reserve.metadata.domain.causation_id != placed.metadata.headers.id
