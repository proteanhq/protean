"""Tests for Message and eventing utilities in utils/eventing.py."""

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import String
from protean.utils.eventing import Message, Metadata


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Account(BaseAggregate):
    name: String(required=True, max_length=100)


class AccountOpened(BaseEvent):
    name: String(required=True)

    class Meta:
        part_of = Account


# ---------------------------------------------------------------------------
# Tests: Message equality, hash, repr, str
# ---------------------------------------------------------------------------
class TestMessageDunderMethods:
    def test_message_eq_same_type(self):
        """Comparing two Message objects of same type."""
        m1 = Message(data={"key": "value"})
        m2 = Message(data={"key": "value"})
        assert m1 == m2

    def test_message_eq_different_type(self):
        """__eq__ returns False for different types."""
        m = Message(data={"key": "value"})
        assert m != "not a message"
        assert m != 42

    def test_message_eq_different_data(self):
        """__eq__ returns False for different data."""
        m1 = Message(data={"key": "value1"})
        m2 = Message(data={"key": "value2"})
        assert m1 != m2

    def test_message_hash(self):
        """Message.__hash__ works for set/dict usage."""
        m1 = Message(data={"key": "value"})
        m2 = Message(data={"key": "value"})
        # Same data -> same hash
        assert hash(m1) == hash(m2)
        # Can be used in a set
        s = {m1, m2}
        assert len(s) == 1

    def test_message_repr(self):
        """Message.__repr__ returns formatted string."""
        m = Message(data={"key": "value"})
        r = repr(m)
        assert r.startswith("<Message:")
        assert "key" in r

    def test_message_str(self):
        """Message.__str__ returns formatted string."""
        m = Message(data={"key": "value"})
        s = str(m)
        assert "Message object" in s
        assert "key" in s


# ---------------------------------------------------------------------------
# Tests: _ensure_headers when headers missing
# ---------------------------------------------------------------------------
class TestEnsureHeaders:
    def test_ensure_headers_creates_headers_when_missing(self, test_domain):
        """_ensure_headers builds headers from scratch."""
        test_domain.register(Account)
        test_domain.register(AccountOpened, part_of=Account)
        test_domain.init(traverse=False)

        event = AccountOpened(name="Alice")
        # Use model_construct to bypass Pydantic validation and create
        # metadata with falsy headers
        original_meta = event._metadata
        fake_meta = Metadata.model_construct(
            headers=None,
            domain=original_meta.domain,
            envelope=original_meta.envelope,
            event_store=None,
        )
        object.__setattr__(event, "_metadata", fake_meta)

        result = Message._ensure_headers(event)
        assert result.headers is not None
        assert result.headers.type == AccountOpened.__type__
