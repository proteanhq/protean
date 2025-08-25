"""Tests for _ReverseCompare class in memory repository"""

from datetime import datetime, date

from protean.adapters.repository.memory import _ReverseCompare


class TestReverseCompareInitialization:
    """Test initialization of _ReverseCompare class"""

    def test_initialization_with_integer(self):
        """Test _ReverseCompare can be initialized with integer"""
        rc = _ReverseCompare(5)
        assert rc.value == 5

    def test_initialization_with_string(self):
        """Test _ReverseCompare can be initialized with string"""
        rc = _ReverseCompare("hello")
        assert rc.value == "hello"

    def test_initialization_with_float(self):
        """Test _ReverseCompare can be initialized with float"""
        rc = _ReverseCompare(3.14)
        assert rc.value == 3.14

    def test_initialization_with_datetime(self):
        """Test _ReverseCompare can be initialized with datetime"""
        dt = datetime(2023, 1, 1, 12, 0, 0)
        rc = _ReverseCompare(dt)
        assert rc.value == dt

    def test_initialization_with_date(self):
        """Test _ReverseCompare can be initialized with date"""
        d = date(2023, 1, 1)
        rc = _ReverseCompare(d)
        assert rc.value == d

    def test_initialization_with_none(self):
        """Test _ReverseCompare can be initialized with None"""
        rc = _ReverseCompare(None)
        assert rc.value is None


class TestReverseCompareBetweenReverseCompareInstances:
    """Test comparisons between two _ReverseCompare instances"""

    def test_less_than_with_reverse_instances(self):
        """Test __lt__ between _ReverseCompare instances reverses the comparison"""
        # rc1 < rc2 means rc1.value > rc2.value
        # So _ReverseCompare(3) < _ReverseCompare(5) means 3 > 5, which is False
        # And _ReverseCompare(5) < _ReverseCompare(3) means 5 > 3, which is True
        rc1 = _ReverseCompare(3)
        rc2 = _ReverseCompare(5)
        assert not (rc1 < rc2)  # 3 > 5 is False
        assert rc2 < rc1  # 5 > 3 is True

    def test_less_than_equal_with_reverse_instances(self):
        """Test __le__ between _ReverseCompare instances"""
        rc1 = _ReverseCompare(3)
        rc2 = _ReverseCompare(5)
        rc3 = _ReverseCompare(3)

        assert not (rc1 <= rc2)  # 3 >= 5 is False
        assert rc1 <= rc3  # 3 >= 3 is True
        assert rc2 <= rc1  # 5 >= 3 is True

    def test_equal_with_reverse_instances(self):
        """Test __eq__ between _ReverseCompare instances"""
        rc1 = _ReverseCompare(5)
        rc2 = _ReverseCompare(5)
        rc3 = _ReverseCompare(3)

        assert rc1 == rc2
        assert not (rc1 == rc3)

    def test_not_equal_with_reverse_instances(self):
        """Test __ne__ between _ReverseCompare instances"""
        rc1 = _ReverseCompare(5)
        rc2 = _ReverseCompare(5)
        rc3 = _ReverseCompare(3)

        assert not (rc1 != rc2)
        assert rc1 != rc3

    def test_greater_than_with_reverse_instances(self):
        """Test __gt__ between _ReverseCompare instances reverses the comparison"""
        rc1 = _ReverseCompare(3)
        rc2 = _ReverseCompare(5)

        assert rc1 > rc2  # 3 < 5 in reverse logic is True
        assert not (rc2 > rc1)  # 5 < 3 in reverse logic is False

    def test_greater_than_equal_with_reverse_instances(self):
        """Test __ge__ between _ReverseCompare instances"""
        rc1 = _ReverseCompare(3)
        rc2 = _ReverseCompare(5)
        rc3 = _ReverseCompare(3)

        assert rc1 >= rc2  # 3 <= 5 in reverse logic is True
        assert rc1 >= rc3  # 3 <= 3 in reverse logic is True
        assert not (rc2 >= rc1)  # 5 <= 3 in reverse logic is False


class TestReverseCompareWithNonReverseValues:
    """Test comparisons between _ReverseCompare and regular values"""

    def test_less_than_with_regular_value(self):
        """Test __lt__ with regular values (should reverse comparison)"""
        rc = _ReverseCompare(3)
        # 3 > 5 should be False, but this is how it's implemented
        assert not (rc < 5)
        # 5 > 3 should be True
        rc2 = _ReverseCompare(5)
        assert rc2 < 3

    def test_less_than_equal_with_regular_value(self):
        """Test __le__ with regular values"""
        rc = _ReverseCompare(3)
        assert rc <= 3  # 3 >= 3 is True
        assert not (rc <= 5)  # 3 >= 5 is False

        rc2 = _ReverseCompare(5)
        assert rc2 <= 3  # 5 >= 3 is True

    def test_equal_with_regular_value(self):
        """Test __eq__ with regular values"""
        rc = _ReverseCompare(5)
        assert rc == 5
        assert not (rc == 3)

    def test_not_equal_with_regular_value(self):
        """Test __ne__ with regular values"""
        rc = _ReverseCompare(5)
        assert not (rc != 5)
        assert rc != 3

    def test_greater_than_with_regular_value(self):
        """Test __gt__ with regular values (should reverse comparison)"""
        rc = _ReverseCompare(3)
        assert rc > 5  # 3 < 5 is True in reverse logic
        assert not (rc > 1)  # 3 < 1 is False in reverse logic

    def test_greater_than_equal_with_regular_value(self):
        """Test __ge__ with regular values"""
        rc = _ReverseCompare(3)
        assert rc >= 3  # 3 <= 3 is True
        assert not (rc >= 1)  # 3 <= 1 is False
        assert rc >= 5  # 3 <= 5 is True


class TestReverseCompareWithDifferentDataTypes:
    """Test _ReverseCompare with different data types"""

    def test_string_comparisons(self):
        """Test string comparisons with _ReverseCompare"""
        rc1 = _ReverseCompare("apple")
        rc2 = _ReverseCompare("banana")

        # rc1 < rc2 means "apple" > "banana", which is False
        # rc2 < rc1 means "banana" > "apple", which is True
        assert not (rc1 < rc2)
        assert rc2 < rc1

    def test_datetime_comparisons(self):
        """Test datetime comparisons with _ReverseCompare"""
        dt1 = datetime(2023, 1, 1)
        dt2 = datetime(2023, 1, 2)

        rc1 = _ReverseCompare(dt1)
        rc2 = _ReverseCompare(dt2)

        # rc1 < rc2 means dt1 > dt2, which is False
        # rc2 < rc1 means dt2 > dt1, which is True
        assert not (rc1 < rc2)
        assert rc2 < rc1

    def test_date_comparisons(self):
        """Test date comparisons with _ReverseCompare"""
        d1 = date(2023, 1, 1)
        d2 = date(2023, 1, 2)

        rc1 = _ReverseCompare(d1)
        rc2 = _ReverseCompare(d2)

        # rc1 < rc2 means d1 > d2, which is False
        # rc2 < rc1 means d2 > d1, which is True
        assert not (rc1 < rc2)
        assert rc2 < rc1

    def test_float_comparisons(self):
        """Test float comparisons with _ReverseCompare"""
        rc1 = _ReverseCompare(3.14)
        rc2 = _ReverseCompare(2.71)

        # rc1 < rc2 means 3.14 > 2.71, which is True
        # rc2 < rc1 means 2.71 > 3.14, which is False
        assert rc1 < rc2
        assert not (rc2 < rc1)

    def test_mixed_numeric_comparisons(self):
        """Test comparisons between int and float in _ReverseCompare"""
        rc_int = _ReverseCompare(3)
        rc_float = _ReverseCompare(3.5)

        # rc_int < rc_float means 3 > 3.5, which is False
        # rc_float < rc_int means 3.5 > 3, which is True
        assert not (rc_int < rc_float)
        assert rc_float < rc_int


class TestReverseCompareRepr:
    """Test __repr__ method of _ReverseCompare"""

    def test_repr_with_integer(self):
        """Test __repr__ with integer value"""
        rc = _ReverseCompare(5)
        assert repr(rc) == "_ReverseCompare(5)"

    def test_repr_with_string(self):
        """Test __repr__ with string value"""
        rc = _ReverseCompare("hello")
        assert repr(rc) == "_ReverseCompare('hello')"

    def test_repr_with_float(self):
        """Test __repr__ with float value"""
        rc = _ReverseCompare(3.14)
        assert repr(rc) == "_ReverseCompare(3.14)"

    def test_repr_with_none(self):
        """Test __repr__ with None value"""
        rc = _ReverseCompare(None)
        assert repr(rc) == "_ReverseCompare(None)"

    def test_repr_with_datetime(self):
        """Test __repr__ with datetime value"""
        dt = datetime(2023, 1, 1, 12, 0, 0)
        rc = _ReverseCompare(dt)
        expected = f"_ReverseCompare({dt!r})"
        assert repr(rc) == expected


class TestReverseCompareSorting:
    """Test _ReverseCompare in sorting contexts"""

    def test_sorting_integers_descending(self):
        """Test sorting integers in descending order using _ReverseCompare"""
        values = [1, 3, 2, 5, 4]
        reverse_values = [_ReverseCompare(v) for v in values]
        sorted_reverse = sorted(reverse_values)

        # Should be sorted in descending order
        expected = [5, 4, 3, 2, 1]
        actual = [rc.value for rc in sorted_reverse]
        assert actual == expected

    def test_sorting_strings_descending(self):
        """Test sorting strings in descending order using _ReverseCompare"""
        values = ["apple", "cherry", "banana", "date"]
        reverse_values = [_ReverseCompare(v) for v in values]
        sorted_reverse = sorted(reverse_values)

        # Should be sorted in descending order
        expected = ["date", "cherry", "banana", "apple"]
        actual = [rc.value for rc in sorted_reverse]
        assert actual == expected

    def test_sorting_mixed_reverse_and_regular(self):
        """Test sorting when mixing _ReverseCompare and regular values"""
        # This tests the edge case mentioned in the comments
        # In practice, this shouldn't happen, but we test the behavior
        rc1 = _ReverseCompare(3)
        rc2 = _ReverseCompare(1)

        # When sorted, _ReverseCompare(3) should come before _ReverseCompare(1)
        # because rc1 < rc2 means 3 > 1, which is True
        sorted_values = sorted([rc1, rc2])
        assert sorted_values[0].value == 3
        assert sorted_values[1].value == 1


class TestReverseCompareEdgeCases:
    """Test edge cases for _ReverseCompare"""

    def test_comparison_with_none_values(self):
        """Test comparisons when values are None"""
        rc1 = _ReverseCompare(None)
        rc2 = _ReverseCompare(None)
        rc3 = _ReverseCompare(5)

        # None == None should be True
        assert rc1 == rc2
        assert not (rc1 != rc2)

        # None != 5 should be True
        assert rc1 != rc3
        assert not (rc1 == rc3)

    def test_chained_comparisons(self):
        """Test chained comparison operations"""
        rc1 = _ReverseCompare(1)
        rc2 = _ReverseCompare(2)
        rc3 = _ReverseCompare(3)

        # rc3 < rc2 < rc1 because 3 > 2 > 1 in reverse logic
        assert rc3 < rc2 < rc1
        assert rc1 > rc2 > rc3

    def test_equality_transitivity(self):
        """Test that equality is transitive"""
        rc1 = _ReverseCompare(5)
        rc2 = _ReverseCompare(5)
        rc3 = _ReverseCompare(5)

        assert rc1 == rc2
        assert rc2 == rc3
        assert rc1 == rc3
