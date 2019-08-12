import pytest

from .elements import CustomBaseContainer, CustomContainer


class TestDataTransferObjectInitialization:
    def test_that_base_container_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            CustomBaseContainer()

    def test_that_a_concrete_custom_container_can_be_instantiated(self):
        custom = CustomContainer(foo='a', bar='b')
        assert custom is not None
