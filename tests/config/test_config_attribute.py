import pytest

from protean.domain.config import Config2, ConfigAttribute


class MockObject:
    def __init__(self):
        self.config = {}


class TestConfig2FromObject:
    """Tests for Config2.from_object() method."""

    def test_from_object_with_dict(self):
        """from_object with a dict normalizes and updates config."""
        config = Config2.load_from_dict()
        config.from_object({"debug": True, "secret_key": "test-secret"})
        assert config["debug"] is True
        assert config["secret_key"] == "test-secret"

    def test_from_object_with_class(self):
        """from_object with a class loads uppercase attributes."""

        class MyConfig:
            DEBUG = True
            SECRET_KEY = "from-class"
            lowercase_ignored = "should not appear"

        config = Config2.load_from_dict()
        config.from_object(MyConfig)
        assert config["debug"] is True
        assert config["secret_key"] == "from-class"
        assert "lowercase_ignored" not in config

    def test_from_object_with_module_like_object(self):
        """from_object with an object having uppercase attrs."""

        class FakeModule:
            TESTING = True
            ENV = "production"

        config = Config2.load_from_dict()
        config.from_object(FakeModule())
        assert config["testing"] is True
        assert config["env"] == "production"


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
