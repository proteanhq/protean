"""Tests for Tasklet Functionality"""
import pytest
from tests.support.dog import Dog

from protean.core.exceptions import UsecaseExecutionError
from protean.core.tasklet import Tasklet
from protean.core.transport import Status
from protean.core.usecase import ShowRequestObject
from protean.core.usecase import ShowUseCase


class TestTasklet:
    """Tests for Tasklet Utility Methods"""

    def test_perform(self):
        """Test call to Tasklet's perform method"""
        Dog.create(id=1, name='Murdock', owner='John')

        # Perform a Show Usecase using Tasklet
        payload = {'identifier': 1}
        response = Tasklet.perform(Dog, ShowUseCase, ShowRequestObject, payload)

        # Validate the response received
        assert response is not None
        assert response.success
        assert response.value.id == 1
        assert response.value.name == 'Murdock'

    def test_raise_error(self):
        """ Test raise error function of the Tasklet """
        with pytest.raises(UsecaseExecutionError) as exc_info:
            Tasklet.perform(Dog, ShowUseCase, ShowRequestObject, {}, raise_error=True)
        assert exc_info.value.value[0] == Status.UNPROCESSABLE_ENTITY
        assert exc_info.value.value[1] == {'code': 422, 'message': {'identifier': 'is required'}}
