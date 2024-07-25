import pytest

from protean.domain.config import ConfigAttribute


class MockObject:
    def __init__(self):
        self.config = {}


class TestConfigAttribute:
    @pytest.fixture
    def mock_obj(self):
        return MockObject()

    @pytest.fixture
    def config_attr(self):
        return ConfigAttribute("test_attribute")

    def test_initialization(self, config_attr):
        assert config_attr.__name__ == "test_attribute"

    def test_get(self, mock_obj, config_attr):
        mock_obj.config["test_attribute"] = "value"
        assert config_attr.__get__(mock_obj) == "value"

    def test_set(self, mock_obj, config_attr):
        config_attr.__set__(mock_obj, "new_value")
        assert mock_obj.config["test_attribute"] == "new_value"

    def test_descriptor_access(self, mock_obj):
        class Example:
            test_attribute = ConfigAttribute("test_attribute")

        example = Example()
        example.config = {"test_attribute": "initial_value"}

        # Test getting the attribute
        assert example.test_attribute == "initial_value"

        # Test setting the attribute
        example.test_attribute = "updated_value"
        assert example.config["test_attribute"] == "updated_value"
