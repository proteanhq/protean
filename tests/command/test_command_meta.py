import warnings
from uuid import uuid4

import pytest

from protean._deprecation import RemovedInProtean10Warning
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()
    name: String()


class Register(BaseCommand):
    user_id: Identifier(identifier=True)
    email: String()
    name: String()


def test_command_definition_without_aggregate_or_stream(test_domain):
    test_domain.register(User, is_event_sourced=True)

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(Register)

    assert (
        exc.value.args[0]
        == "Command `Register` needs to be associated with an aggregate or a stream"
    )


def test_that_abstract_commands_can_be_defined_without_aggregate_or_stream(test_domain):
    class AbstractCommand(BaseCommand):
        foo: String()

    try:
        test_domain.register(AbstractCommand, abstract=True)
    except Exception:
        pytest.fail(
            "Abstract commands should be definable without being associated with an aggregate or a stream"
        )


@pytest.mark.eventstore
def test_command_associated_with_aggregate(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    test_domain.process(
        Register(
            user_id=identifier,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )

    messages = test_domain.event_store.store.read("test::user:command")

    assert len(messages) == 1
    assert messages[0].metadata.headers.stream == f"test::user:command-{identifier}"


@pytest.mark.eventstore
def test_command_associated_with_aggregate_with_custom_stream_name(test_domain):
    test_domain.register(User, is_event_sourced=True, stream_category="foo")
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    test_domain.process(
        Register(
            user_id=identifier,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )

    messages = test_domain.event_store.store.read("test::foo:command")

    assert len(messages) == 1
    assert messages[0].metadata.headers.stream == f"test::foo:command-{identifier}"


def test_aggregate_cluster_of_event(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    assert Register.meta_.aggregate_cluster == User


class TestDeprecatedCommandOptions:
    """`published` is an event-only option that commands silently absorbed with
    no effect. It is deprecated (warn in 0.17, removed at 1.0) and dropped so it
    no longer appears on a command's ``meta_``."""

    @staticmethod
    def _deprecation_messages(record):
        """Messages of the ``RemovedInProtean10Warning`` warnings only — an
        unrelated warning firing first must not shift which one we inspect."""
        return [
            str(w.message)
            for w in record
            if issubclass(w.category, RemovedInProtean10Warning)
        ]

    def test_published_option_warns_on_decorator_path(self, test_domain):
        with pytest.warns(RemovedInProtean10Warning) as record:

            @test_domain.command(part_of=User, published=True)
            class Approve(BaseCommand):
                user_id: Identifier(identifier=True)

        messages = self._deprecation_messages(record)
        assert any("published" in m and "v1.0.0" in m for m in messages)

    def test_published_option_warns_on_register_path(self, test_domain):
        class Suspend(BaseCommand):
            user_id: Identifier(identifier=True)

        with pytest.warns(RemovedInProtean10Warning):
            test_domain.register(Suspend, part_of=User, published=True)

    def test_falsy_deprecated_option_still_warns(self, test_domain):
        # The interception keys on *presence* (``opt in opts``), not truthiness:
        # ``published=False`` is still a category error worth warning about, and a
        # refactor to ``if opts.get(opt)`` would silently stop warning on it.
        class Archive(BaseCommand):
            user_id: Identifier(identifier=True)

        with pytest.warns(RemovedInProtean10Warning) as record:
            test_domain.register(Archive, part_of=User, published=False)

        messages = self._deprecation_messages(record)
        assert any("published" in m for m in messages)
        assert getattr(Archive.meta_, "published", None) is None

    def test_deprecated_option_is_dropped_and_inert(self, test_domain):
        class Rename(BaseCommand):
            user_id: Identifier(identifier=True)

        with pytest.warns(RemovedInProtean10Warning):
            test_domain.register(Rename, part_of=User, published=True)

        # The option is dropped entirely — it does not linger on the command's
        # meta_, and registration otherwise succeeds.
        assert getattr(Rename.meta_, "published", None) is None
        assert Rename.meta_.part_of == User

    def test_command_with_dropped_options_survives_message_conversion(
        self, test_domain
    ):
        # ``Message.from_domain_object`` reads ``meta_.is_fact_event`` (guarded by
        # a ``kind == EVENT`` short-circuit). Drive a real command declared with a
        # dropped option through the full round-trip in-core to prove the command
        # survives message conversion after ``published`` is stripped.
        from protean.utils.eventing import Message

        class Cancel(BaseCommand):
            user_id: Identifier(identifier=True)

        test_domain.register(User, is_event_sourced=True)
        with pytest.warns(RemovedInProtean10Warning):
            test_domain.register(Cancel, part_of=User, published=True)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            identifier = str(uuid4())
            command = Cancel(user_id=identifier)
            message = Message.from_domain_object(command)
            restored = message.to_domain_object()

        assert message.metadata.domain.kind == "COMMAND"
        assert restored.user_id == identifier

    def test_protean_check_flags_deprecated_option(self, test_domain):
        # Acceptance criterion: ``protean check`` reports the usage. The runtime
        # warning is transient, so ``command_factory`` records the dropped options
        # for the IR builder to surface as a ``DEPRECATED_OPTION`` diagnostic.
        from protean.ir.builder import IRBuilder

        class Freeze(BaseCommand):
            user_id: Identifier(identifier=True)

        test_domain.register(User, event_sourced=True)
        with pytest.warns(RemovedInProtean10Warning):
            test_domain.register(Freeze, part_of=User, published=True)
        test_domain.init(traverse=False)

        ir = IRBuilder(test_domain).build()
        option_diags = [
            d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_OPTION"
        ]

        assert len(option_diags) == 1
        assert option_diags[0]["level"] == "warning"
        assert "published" in option_diags[0]["message"]
        assert "v1.0.0" in option_diags[0]["message"]

    def test_clean_command_emits_no_deprecation_warning(self, test_domain):
        with warnings.catch_warnings():
            warnings.simplefilter("error", RemovedInProtean10Warning)

            class Activate(BaseCommand):
                user_id: Identifier(identifier=True)

            # Only valid options — must not warn.
            test_domain.register(Activate, part_of=User)

        assert getattr(Activate.meta_, "published", None) is None

    def test_clean_command_emits_no_check_diagnostic(self, test_domain):
        # Negative guard for the check diagnostic: a command declared with only
        # valid options must not produce a ``DEPRECATED_OPTION`` finding.
        from protean.ir.builder import IRBuilder

        class Enable(BaseCommand):
            user_id: Identifier(identifier=True)

        test_domain.register(User, event_sourced=True)
        test_domain.register(Enable, part_of=User)
        test_domain.init(traverse=False)

        ir = IRBuilder(test_domain).build()
        assert not any(d["code"] == "DEPRECATED_OPTION" for d in ir["diagnostics"])

    def test_deprecated_options_marker_is_cleared_on_re_registration(self, test_domain):
        # A class that already subclasses ``BaseCommand`` is mutated in place by
        # ``derive_element_class`` rather than rebuilt, so ``command_factory``
        # must not leave a stale ``_deprecated_options`` behind from an earlier
        # call: a later registration without deprecated options must clear it.
        class Suspend(BaseCommand):
            user_id: Identifier(identifier=True)

        test_domain.register(User, is_event_sourced=True)
        with pytest.warns(RemovedInProtean10Warning):
            test_domain.register(Suspend, part_of=User, published=True)

        assert Suspend._deprecated_options == ("published",)

        with warnings.catch_warnings():
            warnings.simplefilter("error", RemovedInProtean10Warning)
            test_domain.register(Suspend, part_of=User)

        assert Suspend._deprecated_options == ()

    def test_events_are_unaffected_by_command_deprecation(self, test_domain):
        """The deprecation is command-only: events keep ``published`` live, and
        registering an event with it emits no ``RemovedInProtean10Warning``."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            class OrderPlaced(BaseEvent):
                order_id: Identifier(identifier=True)

            test_domain.register(OrderPlaced, part_of=User, published=True)

        assert not any(isinstance(w.message, RemovedInProtean10Warning) for w in caught)
        # Events still honour the ``published`` option.
        assert OrderPlaced.meta_.published is True
