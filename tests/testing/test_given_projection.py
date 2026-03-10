"""Tests for the projection testing DSL in ``protean.testing``.

Exercises the ``given(event, ...).then(Projection, id=...)`` pipeline
that processes events through projector handlers and validates
resulting projection state.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.fields import Float, Identifier, String
from protean.testing import EventSequence, ProjectionResult, given
from protean.utils.globals import current_domain


# ---------------------------------------------------------------------------
# Domain elements for testing
# ---------------------------------------------------------------------------
class User(BaseAggregate):
    email = String()
    name = String()

    @classmethod
    def register(cls, email: str, name: str):
        user = cls(email=email, name=name)
        user.raise_(Registered(user_id=user.id, email=email, name=name))
        return user


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()
    name = String()


class Transaction(BaseAggregate):
    user_id = Identifier()
    amount = Float()

    @classmethod
    def transact(cls, user_id: str, amount: float):
        transaction = cls(user_id=user_id, amount=amount)
        transaction.raise_(Transacted(user_id=user_id, amount=amount))
        return transaction


class Transacted(BaseEvent):
    user_id = Identifier()
    amount = Float()


class Balances(BaseProjection):
    user_id = Identifier(identifier=True)
    name = String()
    balance = Float()


class TransactionProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        balance = Balances(user_id=event.user_id, name=event.name, balance=0)
        current_domain.repository_for(Balances).add(balance)

    @on(Transacted)
    def on_transacted(self, event: Transacted):
        balance = current_domain.repository_for(Balances).get(event.user_id)
        if balance:
            balance.balance += event.amount
            current_domain.repository_for(Balances).add(balance)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Transaction)
    test_domain.register(Transacted, part_of=Transaction)
    test_domain.register(
        TransactionProjector, projector_for=Balances, aggregates=[Transaction, User]
    )
    test_domain.register(Balances)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: given() polymorphic dispatch
# ---------------------------------------------------------------------------
class TestGivenDispatch:
    def test_given_with_class_returns_aggregate_result(self):
        """given(Class) returns AggregateResult (existing behavior)."""
        from protean.testing import AggregateResult

        result = given(User)
        assert isinstance(result, AggregateResult)

    def test_given_with_events_returns_event_sequence(self):
        """given(event, ...) returns EventSequence when all args are instances."""
        event = Registered(user_id="u1", email="a@b.com", name="Alice")
        result = given(event)
        assert isinstance(result, EventSequence)

    def test_given_with_multiple_events_returns_event_sequence(self):
        """given(event1, event2) returns EventSequence."""
        e1 = Registered(user_id="u1", email="a@b.com", name="Alice")
        e2 = Transacted(user_id="u1", amount=50)
        result = given(e1, e2)
        assert isinstance(result, EventSequence)


# ---------------------------------------------------------------------------
# Tests: EventSequence
# ---------------------------------------------------------------------------
class TestEventSequence:
    def test_repr(self):
        """EventSequence repr shows event type names."""
        e1 = Registered(user_id="u1", email="a@b.com", name="Alice")
        seq = EventSequence([e1])
        assert "Registered" in repr(seq)

    def test_then_returns_projection_result(self):
        """EventSequence.then() returns a ProjectionResult."""
        uid = str(uuid4())
        event = Registered(user_id=uid, email="a@b.com", name="Alice")
        result = given(event).then(Balances, id=uid)
        assert isinstance(result, ProjectionResult)

    def test_then_requires_identity_kwargs(self):
        """then() raises ValueError when no identity keyword is provided."""
        event = Registered(user_id="u1", email="a@b.com", name="Alice")
        with pytest.raises(ValueError, match="at least one keyword argument"):
            given(event).then(Balances)


# ---------------------------------------------------------------------------
# Tests: ProjectionResult — single event
# ---------------------------------------------------------------------------
class TestProjectionResultSingleEvent:
    def test_found_after_single_event(self):
        """Projection is found after processing a single event."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
        ).then(Balances, id=uid)

        assert result.found
        assert not result.not_found

    def test_projection_attributes(self):
        """Projection attributes are accessible via .projection."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
        ).then(Balances, id=uid)

        assert result.projection.name == "Alice"
        assert result.projection.balance == 0

    def test_has_assertion(self):
        """has() validates expected projection attributes."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
        ).then(Balances, id=uid)

        result.has(name="Alice", balance=0)

    def test_has_returns_self(self):
        """has() returns self for chaining."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
        ).then(Balances, id=uid)

        assert result.has(name="Alice") is result


# ---------------------------------------------------------------------------
# Tests: ProjectionResult — multiple events
# ---------------------------------------------------------------------------
class TestProjectionResultMultipleEvents:
    def test_projection_state_after_multiple_events(self):
        """Projection reflects cumulative state from multiple events."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
            Transacted(user_id=uid, amount=100),
        ).then(Balances, id=uid)

        assert result.found
        result.has(name="Alice", balance=100)

    def test_multiple_transactions(self):
        """Multiple transactions accumulate in the projection."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Bob"),
            Transacted(user_id=uid, amount=50),
            Transacted(user_id=uid, amount=75),
        ).then(Balances, id=uid)

        result.has(name="Bob", balance=125)

    def test_proxy_attribute_access(self):
        """Projection attributes are accessible directly on the result."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Charlie"),
            Transacted(user_id=uid, amount=200),
        ).then(Balances, id=uid)

        assert result.name == "Charlie"
        assert result.balance == 200


# ---------------------------------------------------------------------------
# Tests: ProjectionResult — not found
# ---------------------------------------------------------------------------
class TestProjectionResultNotFound:
    def test_not_found_for_different_id(self):
        """Projection is not found when queried with a non-matching ID."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
        ).then(Balances, id="different-id")

        assert result.not_found
        assert not result.found
        assert result.projection is None

    def test_has_raises_on_not_found(self):
        """has() raises AssertionError when projection is not found."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
        ).then(Balances, id="different-id")

        with pytest.raises(AssertionError, match="projection not found"):
            result.has(balance=100)

    def test_proxy_attr_raises_on_not_found(self):
        """Attribute access raises when projection is not found."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
        ).then(Balances, id="different-id")

        with pytest.raises(AttributeError, match="Projection not found"):
            _ = result.balance


# ---------------------------------------------------------------------------
# Tests: ProjectionResult — assertion failures
# ---------------------------------------------------------------------------
class TestProjectionResultAssertionFailures:
    def test_has_raises_on_mismatch(self):
        """has() raises AssertionError with details on attribute mismatch."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
        ).then(Balances, id=uid)

        with pytest.raises(AssertionError, match="expected 'Bob'.*got 'Alice'"):
            result.has(name="Bob")

    def test_has_raises_on_value_mismatch(self):
        """has() raises for numeric mismatches too."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
            Transacted(user_id=uid, amount=100),
        ).then(Balances, id=uid)

        with pytest.raises(AssertionError, match="expected 999"):
            result.has(balance=999)


# ---------------------------------------------------------------------------
# Tests: ProjectionResult — repr and private attrs
# ---------------------------------------------------------------------------
class TestProjectionResultRepr:
    def test_repr_found(self):
        """Repr shows 'found' when projection exists."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
        ).then(Balances, id=uid)

        assert "found" in repr(result)
        assert "Balances" in repr(result)

    def test_repr_not_found(self):
        """Repr shows 'not_found' when projection doesn't exist."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
        ).then(Balances, id="different-id")

        assert "not_found" in repr(result)

    def test_private_attr_raises(self):
        """Accessing private attributes raises AttributeError directly."""
        uid = str(uuid4())
        result = given(
            Registered(user_id=uid, email="a@b.com", name="Alice"),
        ).then(Balances, id=uid)

        with pytest.raises(AttributeError):
            _ = result._some_private
