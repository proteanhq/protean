import pytest

from protean import BaseCommandHandler
from protean.exceptions import NotSupportedError


def test_that_base_command_handler_cannot_be_instantianted():
    with pytest.raises(NotSupportedError):
        BaseCommandHandler()
