"""Test String field sanitization behavior through domain objects.

The framework default is ``sanitize=False``: a String/Text field declared
without an explicit ``sanitize=`` kwarg stores the raw input. Sanitization is
opt-in, either per field (``sanitize=True``) or per domain
(``[field_defaults] sanitize = true``). The tests below cover the framework
default, the explicit-kwarg override, the domain-level default and its
precedence, and the ADR-0026 length re-enforcement that runs only on the
cleaning path.
"""

import bleach
import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Identifier, String, Text


def test_sanitization_option_for_string_fields():
    # Unset by default (the framework default is False, resolved at validation).
    assert String().sanitize is None
    assert String(sanitize=True).sanitize is True
    assert String(sanitize=False).sanitize is False


def test_that_unset_string_values_are_not_cleaned_by_default():
    class RawVO(BaseValueObject):
        name = String()

    vo = RawVO(name="an <script>evil()</script> example")
    # The framework default is False, so the raw input round-trips unchanged.
    assert vo.name == "an <script>evil()</script> example"


def test_that_explicit_sanitize_true_cleans():
    class CleanVO(BaseValueObject):
        name = String(sanitize=True)

    vo = CleanVO(name="an <script>evil()</script> example")
    assert vo.name == "an &lt;script&gt;evil()&lt;/script&gt; example"


def test_that_sanitization_can_be_explicitly_switched_off():
    class RawVO(BaseValueObject):
        name = String(sanitize=False)

    vo = RawVO(name="an <script>evil()</script> example")
    assert vo.name == "an <script>evil()</script> example"


class TestDomainLevelSanitizeDefault:
    """``[field_defaults] sanitize`` sets the default for fields that leave
    ``sanitize`` unset. Precedence: field kwarg > domain default > framework
    default. Exercised through ``Domain.init()`` so the config path is real.
    """

    def _domain(self, sanitize_default=None):
        config = (
            {"field_defaults": {"sanitize": sanitize_default}}
            if sanitize_default is not None
            else {}
        )
        return Domain(name="SanitizeDefaults", config=config)

    def test_domain_default_true_sanitizes_an_unset_field(self):
        class RawVO(BaseValueObject):
            name = String()

        domain = self._domain(sanitize_default=True)
        domain.register(RawVO)
        domain.init(traverse=False)

        with domain.domain_context():
            vo = RawVO(name="an <script>evil()</script> example")
        assert vo.name == "an &lt;script&gt;evil()&lt;/script&gt; example"

    def test_field_kwarg_false_overrides_domain_default_true(self):
        class RawVO(BaseValueObject):
            name = String(sanitize=False)

        domain = self._domain(sanitize_default=True)
        domain.register(RawVO)
        domain.init(traverse=False)

        with domain.domain_context():
            vo = RawVO(name="an <script>evil()</script> example")
        # The explicit field kwarg wins over the domain default.
        assert vo.name == "an <script>evil()</script> example"

    def test_field_kwarg_true_sanitizes_despite_domain_default_unset(self):
        class CleanVO(BaseValueObject):
            name = String(sanitize=True)

        domain = self._domain()  # no field_defaults key
        domain.register(CleanVO)
        domain.init(traverse=False)

        with domain.domain_context():
            vo = CleanVO(name="an <script>evil()</script> example")
        assert vo.name == "an &lt;script&gt;evil()&lt;/script&gt; example"

    def test_domain_default_absent_leaves_an_unset_field_raw(self):
        class RawVO(BaseValueObject):
            name = String()

        domain = self._domain()  # field_defaults defaults to sanitize=False
        domain.register(RawVO)
        domain.init(traverse=False)

        assert domain.config["field_defaults"]["sanitize"] is False
        with domain.domain_context():
            vo = RawVO(name="an <script>evil()</script> example")
        assert vo.name == "an <script>evil()</script> example"

    def test_config_without_field_defaults_key_falls_back_to_false(self):
        # Defensive: if the config is missing the field_defaults section
        # entirely, the resolver falls back to the framework default (do not
        # sanitize) instead of raising.
        class RawVO(BaseValueObject):
            name = String()

        domain = self._domain()
        domain.register(RawVO)
        domain.init(traverse=False)
        domain.config.pop("field_defaults", None)

        with domain.domain_context():
            vo = RawVO(name="an <script>evil()</script> example")
        assert vo.name == "an <script>evil()</script> example"

    def test_domain_default_true_reenforces_length_on_an_unset_field(self):
        # The one interaction that combines both new mechanisms: an unset field
        # (always=False) whose cleaning is turned on by the domain default must
        # still re-enforce max_length on the *sanitized* value (ADR-0026), just
        # like an explicit ``sanitize=True`` field does.
        class NameVO(BaseValueObject):
            name = String(max_length=10)

        domain = self._domain(sanitize_default=True)
        domain.register(NameVO)
        domain.init(traverse=False)

        with domain.domain_context():
            # Raw "&" * 6 is 6 chars (within max_length=10); sanitized it grows
            # to 30 chars, over the limit, so the domain-default path rejects it.
            with pytest.raises(ValidationError) as exc:
                NameVO(name="&" * 6)
            assert "after sanitization" in str(exc.value.messages["name"])

            # A value that stays within bounds after cleaning is accepted and
            # is actually sanitized.
            vo = NameVO(name="a & b")
            assert vo.name == "a &amp; b"

    def test_domain_default_false_leaves_length_re_enforcement_off(self):
        # The mirror case: with the domain default off, an unset field bounds the
        # raw value only, so an input that would grow past max_length on cleaning
        # is accepted verbatim (no post-sanitize length re-check runs).
        class NameVO(BaseValueObject):
            name = String(max_length=10)

        domain = self._domain(sanitize_default=False)
        domain.register(NameVO)
        domain.init(traverse=False)

        with domain.domain_context():
            vo = NameVO(name="&" * 6)
        assert vo.name == "&" * 6

    @pytest.mark.parametrize(
        "raw, sanitizes",
        [
            ("true", True),
            ("True", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("False", False),
            ("0", False),
            ("no", False),
            ("off", False),
            ("", False),
            ("garbage", False),
        ],
    )
    def test_string_config_values_are_coerced_to_a_real_bool(self, raw, sanitizes):
        # Config env-var interpolation only ever yields strings, so a
        # ``[field_defaults] sanitize`` resolved from ``"${VAR|false}"`` arrives
        # as the string ``"false"``. A plain ``bool("false")`` reads True and
        # would silently sanitize, flipping the fail-open contract to
        # fail-closed. The value is parsed instead.
        class RawVO(BaseValueObject):
            name = String()

        domain = self._domain(sanitize_default=raw)
        domain.register(RawVO)
        domain.init(traverse=False)

        raw_html = "an <script>evil()</script> example"
        cleaned = "an &lt;script&gt;evil()&lt;/script&gt; example"
        with domain.domain_context():
            vo = RawVO(name=raw_html)
        assert vo.name == (cleaned if sanitizes else raw_html)


@pytest.mark.no_test_domain
class TestSanitizeDefaultWithoutADomainContext:
    """With no active domain there is no ``[field_defaults] sanitize`` to read,
    so an unset field falls back to the framework default and does not clean.

    The suite's autouse ``test_domain`` fixture pushes a domain context for
    every test, so this class opts out of it with ``no_test_domain`` to reach
    the path a value object built outside a domain actually takes (a
    standalone script, a serializer, a user's own unit test).
    """

    def test_unset_field_stays_raw_with_no_active_domain(self):
        from protean.domain.context import has_domain_context

        assert has_domain_context() is False

        class RawVO(BaseValueObject):
            name = String()

        vo = RawVO(name="an <script>evil()</script> example")
        assert vo.name == "an <script>evil()</script> example"

    def test_explicit_sanitize_true_still_cleans_with_no_active_domain(self):
        # An explicit kwarg does not consult the domain at all, so it cleans
        # whether or not a domain context is active.
        class CleanVO(BaseValueObject):
            name = String(sanitize=True)

        vo = CleanVO(name="an <script>evil()</script> example")
        assert vo.name == "an &lt;script&gt;evil()&lt;/script&gt; example"


class TestLengthBoundsEnforcedOnSanitizedValue:
    """Length bounds (``max_length``/``min_length``, and the implicit ``min_length``
    of a required field) are enforced on the *sanitized* value, so a value
    accepted on write always round-trips through serialization and event-sourced
    replay.

    ``bleach`` both lengthens (``&`` -> ``&amp;``) and shortens (stripping HTML
    comments / disallowed attributes), which could otherwise store a value out of
    bounds that the same field rejects on the way back (:issue:`#1253`). This
    re-enforcement runs only when the field actually cleans, so every field here
    opts in with ``sanitize=True``.
    """

    def test_input_that_escapes_over_max_length_is_rejected(self):
        class NameVO(BaseValueObject):
            name = String(max_length=10, sanitize=True)

        # Raw input is 6 characters (within max_length=10); sanitized it grows to
        # "&amp;" * 6 (30 characters), over the limit.
        with pytest.raises(ValidationError) as exc:
            NameVO(name="&" * 6)

        assert "after sanitization" in str(exc.value.messages["name"])

    def test_max_length_error_reports_the_actual_sanitized_length(self):
        class NameVO(BaseValueObject):
            name = String(max_length=10, sanitize=True)

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
            name = String(max_length=10, sanitize=True)

        # "&" -> "&amp;" (5 chars), so "&&" sanitizes to exactly 10 characters.
        vo = NameVO(name="&&")
        assert vo.name == "&amp;&amp;"
        assert len(vo.name) == 10

    def test_sanitized_length_one_over_max_length_is_rejected(self):
        # Guards the boundary: the check must be strict ``>`` (10 is allowed),
        # not ``>=``.
        class NameVO(BaseValueObject):
            name = String(max_length=9, sanitize=True)

        with pytest.raises(ValidationError):
            NameVO(name="&&")  # sanitizes to 10 characters, over max_length=9

    def test_input_that_shrinks_below_min_length_is_rejected(self):
        class NameVO(BaseValueObject):
            name = String(min_length=8, max_length=50, sanitize=True)

        # Raw input is 26 characters (over min_length=8); bleach strips the
        # comment, leaving "hi" (2 characters), under the minimum.
        with pytest.raises(ValidationError) as exc:
            NameVO(name="hi<!-- padding comment -->")

        assert "below min_length of 8" in str(exc.value.messages["name"])

    def test_required_field_that_sanitizes_to_empty_is_rejected(self):
        class BodyVO(BaseValueObject):
            body = String(required=True, sanitize=True)

        # A required string has an implicit min_length of 1; a comment-only input
        # sanitizes to the empty string.
        with pytest.raises(ValidationError):
            BodyVO(body="<!--nothing here-->")

    def test_value_that_fits_after_sanitization_is_accepted(self):
        class NameVO(BaseValueObject):
            name = String(min_length=4, max_length=20, sanitize=True)

        vo = NameVO(name="Tom & Jerry")
        assert vo.name == "Tom &amp; Jerry"

    def test_accepted_value_round_trips_through_serialization(self):
        class NameVO(BaseValueObject):
            name = String(max_length=20, sanitize=True)

        vo = NameVO(name="Tom & Jerry")
        # The stored (already-escaped) value must be re-acceptable by the same
        # field — bleach idempotency keeps its length stable, so the round-trip
        # holds. This is the guarantee the fix provides.
        again = NameVO(name=vo.name)
        assert again.name == vo.name

    def test_plain_over_max_length_still_rejected_by_core_constraint(self):
        class NameVO(BaseValueObject):
            name = String(max_length=10, sanitize=True)

        with pytest.raises(ValidationError) as exc:
            NameVO(name="a" * 11)

        # No escapable characters, so the core max_length constraint fires with
        # its standard message rather than the post-sanitization check.
        assert "at most 10 characters" in str(exc.value.messages["name"])

    def test_unsanitized_field_bounds_the_raw_value(self):
        class RawVO(BaseValueObject):
            name = String(max_length=10)

        # With the default (no sanitization) the stored value equals the raw
        # input, so a 6-character input with escapable characters is accepted
        # unchanged — the post-sanitize growth never happens, so it is not
        # rejected. This is the write-rejection regression the issue calls out.
        vo = RawVO(name="&" * 6)
        assert vo.name == "&" * 6

    def test_optional_sanitized_field_left_unset_is_accepted(self):
        class NameVO(BaseValueObject):
            label = String(max_length=10, required=True, sanitize=True)
            name = String(max_length=10, required=False, sanitize=True)

        # An optional sanitized field arrives as None; the length check must
        # skip it rather than call len() on None.
        vo = NameVO(label="x")
        assert vo.name is None

    def test_text_field_enforces_min_length_on_sanitized_value(self):
        # The Text half of the advertised contract: Text has no max_length, but
        # min_length is still enforced on the sanitized value.
        class BodyVO(BaseValueObject):
            body = Text(min_length=8, sanitize=True)

        with pytest.raises(ValidationError):
            BodyVO(body="hi<!-- padding comment -->")

        vo = BodyVO(body="a real body")
        assert vo.body == "a real body"


class TestChoicesAreNotSanitized:
    """A ``choices`` field carries a closed vocabulary; its value must match a
    declared choice exactly. HTML-escaping it would break that match, so a
    ``choices`` field is never sanitized even when ``sanitize=True`` is asked for
    (:issue:`#1253`).
    """

    def test_choice_value_with_escapable_chars_is_stored_verbatim(self):
        class NameVO(BaseValueObject):
            name = String(choices=["Tom & Jerry", "Batman"], sanitize=True)

        vo = NameVO(name="Tom & Jerry")
        # Stored verbatim (not "Tom &amp; Jerry"), so it matches the choice.
        assert vo.name == "Tom & Jerry"

    def test_choice_value_round_trips(self):
        class NameVO(BaseValueObject):
            name = String(choices=["Tom & Jerry", "Batman"], sanitize=True)

        stored = NameVO(name="Tom & Jerry").name
        # The stored value is re-acceptable — it still matches the choice list.
        assert NameVO(name=stored).name == "Tom & Jerry"

    def test_non_choice_value_is_still_rejected(self):
        class NameVO(BaseValueObject):
            name = String(choices=["Tom & Jerry", "Batman"], sanitize=True)

        with pytest.raises(ValidationError):
            NameVO(name="Superman")


class TestEventSourcedReplayRoundTrip:
    """The reported bug: an event-sourced aggregate with a sanitized string field
    could not be replayed when the stored value fell outside the field's length
    bounds. With the fix, any accepted value round-trips through replay, and an
    out-of-bounds value is rejected at event creation (:issue:`#1253`). The
    fields opt in with ``sanitize=True`` since sanitization is no longer the
    default.
    """

    @pytest.fixture
    def counter(self, test_domain):
        class Renamed(BaseEvent):
            counter_id = Identifier(required=True)
            name = String(max_length=50, required=True, sanitize=True)

        class Counter(BaseAggregate):
            name = String(max_length=50, sanitize=True)

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
