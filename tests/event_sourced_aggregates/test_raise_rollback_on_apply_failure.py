"""raise_() keeps a rejected event out of an event-sourced aggregate.

When any step of ``raise_()`` raises (an enricher, the ``@apply`` handler,
or an invariant check around it), ``_events``, ``_version`` and
``_event_position`` must be left as they were before the call, and the error
must reach the caller.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.entity import invariant
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import Boolean, Float, Identifier, String


class WalletOpened(BaseEvent):
    wallet_id: Identifier(required=True)


class AmountSet(BaseEvent):
    wallet_id: Identifier(required=True)
    amount: Float(required=True)


class NoteAdded(BaseEvent):
    wallet_id: Identifier(required=True)
    note: String(required=True)


class WalletLocked(BaseEvent):
    wallet_id: Identifier(required=True)


class LabelChanged(BaseEvent):
    wallet_id: Identifier(required=True)
    label: String(required=True)


class Unhandled(BaseEvent):
    wallet_id: Identifier(required=True)


class ChainStarted(BaseEvent):
    wallet_id: Identifier(required=True)


class WalletAborted(BaseEvent):
    wallet_id: Identifier(required=True)


class Abort(BaseException):
    pass


class Wallet(BaseAggregate):
    wallet_id: Identifier(identifier=True)
    amount: Float(min_value=0.01)
    note: String(max_length=50)
    label: String(max_length=50)
    locked: Boolean(default=False)

    @classmethod
    def open(cls, wallet_id):
        wallet = cls._create_new(wallet_id=wallet_id)
        wallet.raise_(WalletOpened(wallet_id=wallet_id))
        return wallet

    @invariant.pre
    def cannot_change_when_locked(self):
        if self.locked:
            raise ValidationError({"_entity": ["Wallet is locked"]})

    @invariant.post
    def label_is_not_forbidden(self):
        if self.label == "forbidden":
            raise ValidationError({"label": ["Label is forbidden"]})

    @apply
    def opened(self, event: WalletOpened):
        self.wallet_id = event.wallet_id

    @apply
    def amount_set(self, event: AmountSet):
        self.amount = event.amount

    @apply
    def note_added(self, event: NoteAdded):
        if event.note == "boom":
            raise ValueError("note rejected: boom")
        self.note = event.note

    @apply
    def wallet_locked(self, event: WalletLocked):
        self.locked = True

    @apply
    def label_changed(self, event: LabelChanged):
        self.label = event.label

    @apply
    def chain_started(self, event: ChainStarted):
        # Raise a second event that its own handler accepts, then fail
        self.raise_(NoteAdded(wallet_id=self.wallet_id, note="chained"))
        raise ValueError("chain rejected")

    @apply
    def wallet_aborted(self, event: WalletAborted):
        raise Abort("aborted")


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Wallet, event_sourced=True)
    test_domain.register(WalletOpened, part_of=Wallet)
    test_domain.register(AmountSet, part_of=Wallet)
    test_domain.register(NoteAdded, part_of=Wallet)
    test_domain.register(WalletLocked, part_of=Wallet)
    test_domain.register(LabelChanged, part_of=Wallet)
    test_domain.register(Unhandled, part_of=Wallet)
    test_domain.register(ChainStarted, part_of=Wallet)
    test_domain.register(WalletAborted, part_of=Wallet)
    test_domain.init(traverse=False)


def _state(wallet):
    return list(wallet._events), wallet._version, wallet._event_position


class TestRejectedEventIsNotRecorded:
    def test_field_validation_failure_in_handler(self):
        wallet = Wallet.open(wallet_id=str(uuid4()))
        events, version, position = _state(wallet)
        assert len(events) == 1

        with pytest.raises(ValidationError) as exc:
            wallet.raise_(AmountSet(wallet_id=wallet.wallet_id, amount=0.0))

        assert "amount" in exc.value.messages
        assert wallet._events == events
        assert wallet._version == version
        assert wallet._event_position == position

    def test_plain_exception_in_handler_reaches_caller_unchanged(self):
        wallet = Wallet.open(wallet_id=str(uuid4()))
        events, version, position = _state(wallet)

        with pytest.raises(ValueError) as exc:
            wallet.raise_(NoteAdded(wallet_id=wallet.wallet_id, note="boom"))

        assert type(exc.value) is ValueError
        assert str(exc.value) == "note rejected: boom"
        assert wallet._events == events
        assert wallet._version == version
        assert wallet._event_position == position

    def test_post_invariant_failure(self):
        wallet = Wallet.open(wallet_id=str(uuid4()))
        events, version, position = _state(wallet)

        with pytest.raises(ValidationError) as exc:
            wallet.raise_(LabelChanged(wallet_id=wallet.wallet_id, label="forbidden"))

        assert exc.value.messages == {"label": ["Label is forbidden"]}
        assert wallet._events == events
        assert wallet._version == version
        assert wallet._event_position == position

    def test_pre_invariant_failure(self):
        wallet = Wallet.open(wallet_id=str(uuid4()))
        wallet.raise_(WalletLocked(wallet_id=wallet.wallet_id))
        events, version, position = _state(wallet)
        assert len(events) == 2

        with pytest.raises(ValidationError) as exc:
            wallet.raise_(LabelChanged(wallet_id=wallet.wallet_id, label="new"))

        assert exc.value.messages == {"_entity": ["Wallet is locked"]}
        assert wallet._events == events
        assert wallet._version == version
        assert wallet._event_position == position
        assert wallet._disable_invariant_checks is False

    def test_missing_apply_handler(self):
        wallet = Wallet.open(wallet_id=str(uuid4()))
        events, version, position = _state(wallet)

        with pytest.raises(IncorrectUsageError, match="No @apply handler registered"):
            wallet.raise_(Unhandled(wallet_id=wallet.wallet_id))

        assert wallet._events == events
        assert wallet._version == version
        assert wallet._event_position == position

    def test_base_exception_in_handler(self):
        wallet = Wallet.open(wallet_id=str(uuid4()))
        events, version, position = _state(wallet)

        with pytest.raises(Abort):
            wallet.raise_(WalletAborted(wallet_id=wallet.wallet_id))

        assert wallet._events == events
        assert wallet._version == version
        assert wallet._event_position == position

    def test_event_raised_inside_failing_handler_is_dropped_too(self):
        wallet = Wallet.open(wallet_id=str(uuid4()))
        events, version, position = _state(wallet)

        with pytest.raises(ValueError, match="chain rejected"):
            wallet.raise_(ChainStarted(wallet_id=wallet.wallet_id))

        assert wallet._events == events
        assert wallet._version == version
        assert wallet._event_position == position

    def test_enricher_failure(self, test_domain):
        wallet = Wallet.open(wallet_id=str(uuid4()))
        events, version, position = _state(wallet)

        def failing_enricher(event, aggregate):
            raise RuntimeError("enricher failed")

        test_domain.register_event_enricher(failing_enricher)

        with pytest.raises(RuntimeError, match="enricher failed"):
            wallet.raise_(NoteAdded(wallet_id=wallet.wallet_id, note="hello"))

        assert wallet.note is None
        assert wallet._events == events
        assert wallet._version == version
        assert wallet._event_position == position


class TestRecoveryAfterRejection:
    def test_next_valid_event_takes_the_rejected_events_slot(self):
        wallet = Wallet.open(wallet_id=str(uuid4()))
        events, version, position = _state(wallet)

        with pytest.raises(ValidationError):
            wallet.raise_(AmountSet(wallet_id=wallet.wallet_id, amount=0.0))

        wallet.raise_(AmountSet(wallet_id=wallet.wallet_id, amount=5.0))

        assert wallet.amount == 5.0
        assert wallet._version == version + 1
        assert wallet._event_position == position + 1
        assert len(wallet._events) == len(events) + 1
        assert wallet._events[: len(events)] == events

        new_event = wallet._events[-1]
        assert isinstance(new_event, AmountSet)
        assert new_event.amount == 5.0
        assert new_event._metadata.headers.id.endswith(f"-{version + 1}")
        assert new_event._metadata.domain.sequence_id == f"{version + 1}"
        assert new_event._expected_version == position

    @pytest.mark.eventstore
    def test_persist_and_reload_after_rejection(self, test_domain):
        wallet = Wallet.open(wallet_id=str(uuid4()))

        with pytest.raises(ValidationError):
            wallet.raise_(AmountSet(wallet_id=wallet.wallet_id, amount=0.0))

        wallet.raise_(AmountSet(wallet_id=wallet.wallet_id, amount=5.0))
        test_domain.repository_for(Wallet).add(wallet)

        loaded = test_domain.repository_for(Wallet).get(wallet.wallet_id)

        assert loaded.amount == 5.0
        assert loaded._version == wallet._version == 1

        stored = test_domain.event_store.store.read(
            f"{Wallet.meta_.stream_category}-{wallet.wallet_id}"
        )
        assert [message.metadata.headers.type for message in stored] == [
            WalletOpened.__type__,
            AmountSet.__type__,
        ]


class TestSuccessfulRaiseIsUnchanged:
    def test_successful_raise_records_exactly_one_event(self):
        wallet = Wallet.open(wallet_id=str(uuid4()))
        events, version, position = _state(wallet)

        wallet.raise_(NoteAdded(wallet_id=wallet.wallet_id, note="hello"))

        assert wallet.note == "hello"
        assert wallet._version == version + 1
        assert wallet._event_position == position + 1
        assert wallet._events[:-1] == events
        assert isinstance(wallet._events[-1], NoteAdded)
