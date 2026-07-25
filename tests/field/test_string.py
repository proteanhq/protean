"""Test String field sanitization behavior through domain objects."""

import bleach
import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Identifier, String, Text


def test_sanitization_option_for_string_fields():
    str_field1 = String()
    assert str_field1.sanitize is True

    str_field1 = String(sanitize=False)
    assert str_field1.sanitize is False


def test_that_string_values_are_automatically_cleaned():
    class CleanVO(BaseValueObject):
        name = String()

    vo = CleanVO(name="an <script>evil()</script> example")
    assert vo.name == "an &lt;script&gt;evil()&lt;/script&gt; example"


def test_that_sanitization_can_be_optionally_switched_off():
    class RawVO(BaseValueObject):
        name = String(sanitize=False)

    vo = RawVO(name="an <script>evil()</script> example")
    assert vo.name == "an <script>evil()</script> example"


class TestLengthBoundsEnforcedOnSanitizedValue:
    """Length bounds (``max_length``/``min_length``, and the implicit ``min_length``
    of a required field) are enforced on the *sanitized* value, so a value
    accepted on write always round-trips through serialization and event-sourced
    replay.

    ``bleach`` both lengthens (``&`` -> ``&amp;``) and shortens (stripping HTML
    comments / disallowed attributes), which could otherwise store a value out of
    bounds that the same field rejects on the way back (:issue:`#1253`).
    """

    def test_input_that_escapes_over_max_length_is_rejected(self):
        class NameVO(BaseValueObject):
            name = String(max_length=10)

        # Raw input is 6 characters (within max_length=10); sanitized it grows to
        # "&amp;" * 6 (30 characters), over the limit.
        with pytest.raises(ValidationError) as exc:
            NameVO(name="&" * 6)

        assert "after sanitization" in str(exc.value.messages["name"])

    def test_max_length_error_reports_the_actual_sanitized_length(self):
        class NameVO(BaseValueObject):
            name = String(max_length=10)

        with pytest.raises(ValidationError) as exc:
            NameVO(name="&" * 6)

        # Derive the expected length from bleach rather than hard-coding it, so
        # the test pins the reported value to the real sanitized length.
        sanitized_length = len(bleach.clean("&" * 6))
        message = str(exc.value.messages["name"])
        assert f"{sanitized_length} characters after sanitization" in message
        assert "max_length of 10" in message

    def test_sanitized_length_exactly_at_max_length_is_accepted(self):
        class NameVO(BaseValueObject):
            name = String(max_length=10)

        # "&" -> "&amp;" (5 chars), so "&&" sanitizes to exactly 10 characters.
        vo = NameVO(name="&&")
        assert vo.name == "&amp;&amp;"
        assert len(vo.name) == 10

    def test_sanitized_length_one_over_max_length_is_rejected(self):
        # Guards the boundary: the check must be strict ``>`` (10 is allowed),
        # not ``>=``.
        class NameVO(BaseValueObject):
            name = String(max_length=9)

        with pytest.raises(ValidationError):
            NameVO(name="&&")  # sanitizes to 10 characters, over max_length=9

    def test_input_that_shrinks_below_min_length_is_rejected(self):
        class NameVO(BaseValueObject):
            name = String(min_length=8, max_length=50)

        # Raw input is 26 characters (over min_length=8); bleach strips the
        # comment, leaving "hi" (2 characters), under the minimum.
        with pytest.raises(ValidationError) as exc:
            NameVO(name="hi<!-- padding comment -->")

        assert "below min_length of 8" in str(exc.value.messages["name"])

    def test_required_field_that_sanitizes_to_empty_is_rejected(self):
        class BodyVO(BaseValueObject):
            body = String(required=True)

        # A required string has an implicit min_length of 1; a comment-only input
        # sanitizes to the empty string.
        with pytest.raises(ValidationError):
            BodyVO(body="<!--nothing here-->")

    def test_value_that_fits_after_sanitization_is_accepted(self):
        class NameVO(BaseValueObject):
            name = String(min_length=4, max_length=20)

        vo = NameVO(name="Tom & Jerry")
        assert vo.name == "Tom &amp; Jerry"

    def test_accepted_value_round_trips_through_serialization(self):
        class NameVO(BaseValueObject):
            name = String(max_length=20)

        vo = NameVO(name="Tom & Jerry")
        # The stored (already-escaped) value must be re-acceptable by the same
        # field — bleach idempotency keeps its length stable, so the round-trip
        # holds. This is the guarantee the fix provides.
        again = NameVO(name=vo.name)
        assert again.name == vo.name

    def test_plain_over_max_length_still_rejected_by_core_constraint(self):
        class NameVO(BaseValueObject):
            name = String(max_length=10)

        with pytest.raises(ValidationError) as exc:
            NameVO(name="a" * 11)

        # No escapable characters, so the core max_length constraint fires with
        # its standard message rather than the post-sanitization check.
        assert "at most 10 characters" in str(exc.value.messages["name"])

    def test_sanitize_false_bounds_the_raw_value(self):
        class RawVO(BaseValueObject):
            name = String(max_length=10, sanitize=False)

        # Without sanitization the stored value equals the raw input, so a
        # 6-character input with escapable characters is accepted unchanged.
        vo = RawVO(name="&" * 6)
        assert vo.name == "&" * 6

    def test_optional_field_left_unset_is_accepted(self):
        class NameVO(BaseValueObject):
            label = String(max_length=10, required=True)
            name = String(max_length=10, required=False)

        # An optional sanitized field arrives as None; the length check must
        # skip it rather than call len() on None.
        vo = NameVO(label="x")
        assert vo.name is None

    def test_text_field_enforces_min_length_on_sanitized_value(self):
        # The Text half of the advertised contract: Text has no max_length, but
        # min_length is still enforced on the sanitized value.
        class BodyVO(BaseValueObject):
            body = Text(min_length=8)

        with pytest.raises(ValidationError):
            BodyVO(body="hi<!-- padding comment -->")

        vo = BodyVO(body="a real body")
        assert vo.body == "a real body"


class TestChoicesAreNotSanitized:
    """A ``choices`` field carries a closed vocabulary; its value must match a
    declared choice exactly. HTML-escaping it would break that match, so a
    ``choices`` field is never sanitized (:issue:`#1253`).
    """

    def test_choice_value_with_escapable_chars_is_stored_verbatim(self):
        class NameVO(BaseValueObject):
            name = String(choices=["Tom & Jerry", "Batman"])

        vo = NameVO(name="Tom & Jerry")
        # Stored verbatim (not "Tom &amp; Jerry"), so it matches the choice.
        assert vo.name == "Tom & Jerry"

    def test_choice_value_round_trips(self):
        class NameVO(BaseValueObject):
            name = String(choices=["Tom & Jerry", "Batman"])

        stored = NameVO(name="Tom & Jerry").name
        # The stored value is re-acceptable — it still matches the choice list.
        assert NameVO(name=stored).name == "Tom & Jerry"

    def test_non_choice_value_is_still_rejected(self):
        class NameVO(BaseValueObject):
            name = String(choices=["Tom & Jerry", "Batman"])

        with pytest.raises(ValidationError):
            NameVO(name="Superman")


class TestEventSourcedReplayRoundTrip:
    """The reported bug: an event-sourced aggregate with a sanitized string field
    could not be replayed when the stored value fell outside the field's length
    bounds. With the fix, any accepted value round-trips through replay, and an
    out-of-bounds value is rejected at event creation (:issue:`#1253`).
    """

    @pytest.fixture
    def counter(self, test_domain):
        class Renamed(BaseEvent):
            counter_id = Identifier(required=True)
            name = String(max_length=50, required=True)

        class Counter(BaseAggregate):
            name = String(max_length=50)

            @apply
            def on_renamed(self, event: Renamed) -> None:
                self.name = event.name

        test_domain.register(Counter, event_sourced=True)
        test_domain.register(Renamed, part_of=Counter)
        test_domain.init(traverse=False)

        return Counter, Renamed

    def test_value_with_escapable_chars_replays_cleanly(self, counter):
        Counter, Renamed = counter

        replayed = Counter.from_events([Renamed(counter_id="1", name="R&D <team>")])

        # The sanitized value survives reconstitution unchanged.
        assert replayed.name == "R&amp;D &lt;team&gt;"

    def test_event_serializes_and_deserializes_within_bounds(self, counter):
        _, Renamed = counter

        event = Renamed(counter_id="1", name="R&D <team>")
        payload = event.to_dict()
        # Deserializing the stored (already-sanitized) payload must not exceed the
        # field's bounds — the real serialize -> store -> replay round-trip.
        restored = Renamed(counter_id=payload["counter_id"], name=payload["name"])
        assert restored.name == event.name

    def test_over_limit_value_is_rejected_at_event_creation(self, counter):
        _, Renamed = counter

        # 11 raw "&" escape to 55 characters; the event can never carry an
        # unreplayable value, so the write is rejected before it is stored.
        with pytest.raises(ValidationError) as exc:
            Renamed(counter_id="1", name="&" * 11)

        assert "after sanitization" in str(exc.value.messages["name"])
