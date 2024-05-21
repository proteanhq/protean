"""Test `atomic_change` context manager"""

import pytest

from protean import BaseAggregate, atomic_change, invariant
from protean.fields import Integer
from protean.exceptions import ValidationError


class TestAtomicChange:
    def test_atomic_change_context_manager(self):
        class TestAggregate(BaseAggregate):
            pass

        aggregate = TestAggregate()

        with atomic_change(aggregate):
            assert aggregate._disable_invariant_checks is True

        assert aggregate._disable_invariant_checks is False

    def test_clean_is_not_triggered_within_context_manager(self, test_domain):
        class TestAggregate(BaseAggregate):
            value1 = Integer()
            value2 = Integer()

            @invariant
            def raise_error(self):
                if self.value2 != self.value1 + 1:
                    raise ValidationError({"_entity": ["Invariant error"]})

        test_domain.register(TestAggregate)
        test_domain.init(traverse=False)

        aggregate = TestAggregate(value1=1, value2=2)

        # This raises an error because of the invariant
        with pytest.raises(ValidationError):
            aggregate.value1 = 2
            aggregate.value2 = 3

        # This should not raise an error because of the context manager
        with atomic_change(aggregate):
            aggregate.value1 = 2
            aggregate.value2 = 3
