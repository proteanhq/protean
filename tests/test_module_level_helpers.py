"""The helpers that build message metadata and record events are module-level
functions, so a user subclass that defines a method of the same name does not
replace them."""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.fields import Identifier, String

_SHADOWED = (
    "_next_event_identity",
    "_recorded_event_headers",
    "_run_event_enrichers",
    "_parent_command_lineage",
    "_command_headers",
    "_enriched_domain_fields",
    "_parent_event_lineage",
    "_event_headers",
    "_raised_domain_fields",
    "_resolve_message_lineage",
    "_assemble_message_metadata",
)


def _raising(name):
    def method(self, *args, **kwargs):
        raise AssertionError(f"{name} on the subclass was called")

    return method


def _shadowing(base, name, annotations):
    namespace = {name: _raising(name) for name in _SHADOWED}
    namespace["__annotations__"] = annotations
    namespace["__module__"] = __name__
    return type(name, (base,), namespace)


Account = _shadowing(
    BaseAggregate,
    "Account",
    {"id": Identifier(identifier=True), "name": String()},
)
Open = _shadowing(BaseCommand, "Open", {"account_id": Identifier(identifier=True)})
Opened = _shadowing(BaseEvent, "Opened", {"account_id": Identifier(identifier=True)})


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(Open, part_of=Account)
    test_domain.register(Opened, part_of=Account)
    test_domain.init(traverse=False)


def test_shadowing_methods_exist_on_the_subclasses():
    for cls in (Account, Open, Opened):
        for name in _SHADOWED:
            assert name in vars(cls)


def test_command_metadata_ignores_shadowing_methods():
    command = Open(account_id=str(uuid4()))

    assert command._metadata.headers.type == Open.__type__
    assert command._metadata.headers.time is not None
    assert command._metadata.domain.kind == "COMMAND"


def test_raise_ignores_shadowing_methods():
    account = Account(name="Primary")
    account_id = account.id

    account.raise_(Opened(account_id=account_id))

    assert len(account._events) == 1
    event = account._events[0]
    assert event._metadata.headers.type == Opened.__type__
    assert event._metadata.headers.id == f"test::account-{account_id}-0.1"
    assert event._metadata.domain.stream_category == "test::account"
