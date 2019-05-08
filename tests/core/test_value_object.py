"""Tests for ValueObject Functionality and Base Classes"""

# Protean
import pytest


class TestValueObject:
    """Tests for Core Value Object functionality"""

    @pytest.mark.pending
    def test_init(self):
        """Test that a Value Object can be instantiated successfully"""

    @pytest.mark.pending
    def test_value_object_non_persistence(self):
        """Test that a pure constructed value object cannot be persisted"""

    @pytest.mark.pending
    def test_value_object_data_persistence(self):
        """Test that a Value Object is persisted along with its parent Entity"""

    @pytest.mark.pending
    def test_value_object_persistence(self):
        """Test that a Value Object can be persisted into its own data store"""

    @pytest.mark.pending
    def test_value_equivalence(self):
        """Test that the values of two value objects are used during comparison"""

    @pytest.mark.pending
    def test_hash(self):
        """Test that values of a value object are used to generate unique hash"""

    @pytest.mark.pending
    def test_simplicity(self):
        """Test that only simple fields are permitted in Value Objects, and no associations"""
