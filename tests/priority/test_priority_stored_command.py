"""The stored command records the priority it was processed with.

``domain.process()`` resolves a priority from its ``priority=`` argument or
the ``processing_priority()`` context. The command written to the event store
must carry that priority, so the server handles a deferred command, and routes
the events it raises, at the same priority.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.utils.globals import current_domain
from protean.utils.mixins import handle
from protean.utils.processing import Priority, processing_priority

pytestmark = pytest.mark.no_test_domain


class Gadget(BaseAggregate):
    name: String(max_length=100, required=True)

    def activate(self):
        self.raise_(GadgetActivated(gadget_id=self.id, name=self.name))


class GadgetActivated(BaseEvent):
    gadget_id: String(required=True)
    name: String(required=True)


class CreateGadget(BaseCommand):
    gadget_id: Identifier(identifier=True)
    name: String(required=True)


class GadgetCommandHandler(BaseCommandHandler):
    @handle(CreateGadget)
    def create_gadget(self, command: CreateGadget):
        gadget = Gadget(id=command.gadget_id, name=command.name)
        gadget.activate()
        current_domain.repository_for(Gadget).add(gadget)


class RegisterGadget(BaseCommand):
    gadget_id: Identifier(identifier=True)
    name: String(required=True)


class GadgetRegistrationHandler(BaseCommandHandler):
    @handle(RegisterGadget)
    def register_gadget(self, command: RegisterGadget):
        current_domain.process(
            CreateGadget(gadget_id=f"{command.gadget_id}-child", name=command.name)
        )


def _run_on_engine(domain, handler_cls, message):
    engine = Engine(domain=domain, test_mode=True)
    try:
        return engine.loop.run_until_complete(
            engine.handle_message(handler_cls, message)
        )
    finally:
        engine.loop.close()


def _build_domain(command_processing: str):
    from protean.domain import Domain

    domain = Domain(name="Test")
    domain.config["enable_outbox"] = True
    domain.config["server"]["default_subscription_type"] = "stream"
    domain.config["command_processing"] = command_processing
    domain.config["event_processing"] = "sync"

    domain.register(Gadget)
    domain.register(GadgetActivated, part_of=Gadget)
    domain.register(CreateGadget, part_of=Gadget)
    domain.register(GadgetCommandHandler, part_of=Gadget)
    domain.register(RegisterGadget, part_of=Gadget)
    domain.register(GadgetRegistrationHandler, part_of=Gadget)
    domain.init(traverse=False)
    return domain


@pytest.fixture
def async_domain():
    domain = _build_domain("async")
    with domain.domain_context():
        yield domain


@pytest.fixture
def sync_domain():
    domain = _build_domain("sync")
    with domain.domain_context():
        yield domain


def _stored_command(domain, gadget_id):
    message = domain.event_store.store.read_last_message(
        f"test::gadget:command-{gadget_id}"
    )
    assert message is not None
    return message


def _outbox_records_for(domain, event_cls):
    outbox_repo = domain._get_outbox_repo("default")
    return [r for r in outbox_repo.find_unprocessed() if r.type == event_cls.__type__]


class TestAsyncCommandKeepsPriority:
    def test_explicit_priority_is_stored(self, async_domain):
        async_domain.process(CreateGadget(gadget_id="g-1", name="A"), priority=-50)

        stored = _stored_command(async_domain, "g-1")
        assert stored.metadata.domain.asynchronous is True
        assert stored.metadata.domain.priority == -50

    def test_context_priority_is_stored(self, async_domain):
        with processing_priority(Priority.BULK):
            async_domain.process(CreateGadget(gadget_id="g-2", name="B"))

        stored = _stored_command(async_domain, "g-2")
        assert stored.metadata.domain.priority == Priority.BULK

    def test_explicit_priority_overrides_context(self, async_domain):
        with processing_priority(Priority.LOW):
            async_domain.process(
                CreateGadget(gadget_id="g-3", name="C"), priority=Priority.HIGH
            )

        stored = _stored_command(async_domain, "g-3")
        assert stored.metadata.domain.priority == Priority.HIGH

    def test_default_priority_is_normal(self, async_domain):
        async_domain.process(CreateGadget(gadget_id="g-4", name="D"))

        stored = _stored_command(async_domain, "g-4")
        assert stored.metadata.domain.priority == Priority.NORMAL

    def test_rebuilt_command_keeps_stored_priority(self, async_domain):
        async_domain.process(
            CreateGadget(gadget_id="g-5", name="E"), priority=Priority.BULK
        )

        rebuilt = _stored_command(async_domain, "g-5").to_domain_object()
        assert isinstance(rebuilt, CreateGadget)
        assert rebuilt._metadata.domain.priority == Priority.BULK

    def test_server_routes_raised_events_at_stored_priority(self, async_domain):
        async_domain.process(
            CreateGadget(gadget_id="g-6", name="F"), priority=Priority.BULK
        )
        # Deferred: the handler has not run, so nothing is in the outbox yet.
        assert _outbox_records_for(async_domain, GadgetActivated) == []

        stored = _stored_command(async_domain, "g-6")
        result = _run_on_engine(async_domain, GadgetCommandHandler, stored)

        assert result is True
        records = _outbox_records_for(async_domain, GadgetActivated)
        assert len(records) == 1
        assert records[0].priority == Priority.BULK

    def test_child_command_from_server_handler_keeps_stored_priority(
        self, async_domain
    ):
        async_domain.process(
            RegisterGadget(gadget_id="g-7", name="G"), priority=Priority.BULK
        )

        stored = _stored_command(async_domain, "g-7")
        result = _run_on_engine(async_domain, GadgetRegistrationHandler, stored)

        assert result is True
        child = _stored_command(async_domain, "g-7-child")
        assert child.metadata.domain.priority == Priority.BULK


class TestSyncCommandKeepsPriority:
    def test_explicit_priority_is_stored(self, sync_domain):
        sync_domain.process(
            CreateGadget(gadget_id="s-1", name="A"), priority=Priority.LOW
        )

        stored = _stored_command(sync_domain, "s-1")
        assert stored.metadata.domain.asynchronous is False
        assert stored.metadata.domain.priority == Priority.LOW

    def test_context_priority_is_stored(self, sync_domain):
        with processing_priority(Priority.HIGH):
            sync_domain.process(CreateGadget(gadget_id="s-2", name="B"))

        stored = _stored_command(sync_domain, "s-2")
        assert stored.metadata.domain.priority == Priority.HIGH
