from datetime import datetime
from uuid import uuid4

from protean.adapters.repository.memory import (
    Contains,
    Endswith,
    Exact,
    GreaterThan,
    GreaterThanOrEqual,
    IContains,
    IExact,
    In,
    LessThan,
    LessThanOrEqual,
    Any,
    Startswith,
)


class TestLookup:
    """This class holds tests for Lookup Class"""

    from protean.adapters.repository.memory import MemoryLookup, MemoryProvider
    from protean.port.dao import BaseLookup

    @MemoryProvider.register_lookup
    class SampleLookup(MemoryLookup):
        """A simple implementation of lookup class"""

        lookup_name = "sample"

        def evaluate(self):
            return self.source == self.target

    def test_initialization_of_a_lookup_object(self):
        lookup = self.SampleLookup("src", "src")
        assert lookup.evaluate() is True

    def test_registration_of_a_lookup_to_an_adapter(self):
        from protean.adapters.repository.memory import MemoryProvider

        assert MemoryProvider.get_lookups().get("sample") is not None


class TestExact:
    def test_string_match(self):
        assert Exact("John", "John").evaluate() is True
        assert Exact("John", "Jane").evaluate() is False

    def test_integer_match(self):
        assert Exact(42, 42).evaluate() is True
        assert Exact(42, 43).evaluate() is False

    def test_datetime_match(self):
        now = datetime.today()
        assert Exact(now, now).evaluate() is True

    def test_date_match(self):
        today = datetime.today().date()
        assert Exact(today, today).evaluate() is True

    def test_uuid_match(self):
        uid = uuid4()
        assert Exact(uid, uid).evaluate() is True
        assert Exact(uid, uuid4()).evaluate() is False

    def test_uuid_to_string_match(self):
        uid = uuid4()
        assert Exact(uid, str(uid)).evaluate() is True


class TestIExact:
    def test_case_insensitive_match(self):
        assert IExact("John", "john").evaluate() is True
        assert IExact("HELLO", "hello").evaluate() is True
        assert IExact("Hello", "World").evaluate() is False


class TestContains:
    def test_substring_match(self):
        assert Contains("Hello World", "World").evaluate() is True
        assert Contains("Hello World", "xyz").evaluate() is False

    def test_case_sensitive(self):
        assert Contains("Hello World", "hello").evaluate() is False


class TestIContains:
    def test_case_insensitive_substring_match(self):
        assert IContains("Hello World", "hello").evaluate() is True
        assert IContains("Hello World", "WORLD").evaluate() is True
        assert IContains("Hello World", "xyz").evaluate() is False


class TestStartswith:
    def test_prefix_match(self):
        assert Startswith("Hello World", "Hello").evaluate() is True
        assert Startswith("Hello World", "World").evaluate() is False


class TestEndswith:
    def test_suffix_match(self):
        assert Endswith("Hello World", "World").evaluate() is True
        assert Endswith("Hello World", "Hello").evaluate() is False


class TestComparisons:
    def test_greater_than(self):
        assert GreaterThan(10, 5).evaluate() is True
        assert GreaterThan(5, 10).evaluate() is False
        assert GreaterThan(5, 5).evaluate() is False

    def test_greater_than_or_equal(self):
        assert GreaterThanOrEqual(10, 5).evaluate() is True
        assert GreaterThanOrEqual(5, 5).evaluate() is True
        assert GreaterThanOrEqual(4, 5).evaluate() is False

    def test_less_than(self):
        assert LessThan(5, 10).evaluate() is True
        assert LessThan(10, 5).evaluate() is False
        assert LessThan(5, 5).evaluate() is False

    def test_less_than_or_equal(self):
        assert LessThanOrEqual(5, 10).evaluate() is True
        assert LessThanOrEqual(5, 5).evaluate() is True
        assert LessThanOrEqual(6, 5).evaluate() is False

    def test_datetime_comparison(self):
        earlier = datetime(2024, 1, 1)
        later = datetime(2024, 12, 31)
        assert GreaterThan(later, earlier).evaluate() is True
        assert LessThan(earlier, later).evaluate() is True


class TestIn:
    def test_value_in_list(self):
        assert In(30, [20, 30, 40]).evaluate() is True
        assert In(50, [20, 30, 40]).evaluate() is False

    def test_string_in_list(self):
        assert In("admin", ["admin", "user"]).evaluate() is True
        assert In("guest", ["admin", "user"]).evaluate() is False

    def test_single_value_target(self):
        assert In(5, 5).evaluate() is True
        assert In(5, 6).evaluate() is False


class TestAny:
    def test_any_overlap(self):
        assert Any(["a", "b"], ["b", "c"]).evaluate() is True
        assert Any(["a", "b"], ["c", "d"]).evaluate() is False

    def test_single_value_source(self):
        assert Any("b", ["a", "b", "c"]).evaluate() is True
        assert Any("d", ["a", "b", "c"]).evaluate() is False
