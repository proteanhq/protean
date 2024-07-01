import pytest

from protean.core.event_sourced_repository import BaseEventSourcedRepository
from protean.exceptions import NotSupportedError


def test_event_sourced_aggregate_cannot_be_initialized():
    with pytest.raises(NotSupportedError) as exc:
        BaseEventSourcedRepository()

    assert str(exc.value) == "BaseEventSourcedRepository cannot be instantiated"
