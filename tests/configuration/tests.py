import os

import pytest

from protean.domain import Domain
from protean.domain.config import Config

# config keys used for the TestConfig
TEST_KEY = "foo"
SECRET_KEY = "config"
non_key = "not-a-key"


def common_object_test(domain):
    assert domain.secret_key == "config"
    assert domain.config["TEST_KEY"] == "foo"
    assert "TestConfig" not in domain.config
    assert "non_key" not in domain.config


class TestConfig:
    def test_config_attribute_set(self):
        domain = Domain(__name__)
        domain.config.from_pyfile(__file__.rsplit(".", 1)[0] + ".py")
        domain.secret_key = "Baz"

        assert domain.secret_key == "Baz"
        assert domain.config["SECRET_KEY"] == "Baz"

    def test_config_from_file(self):
        domain = Domain(__name__)
        domain.config.from_pyfile(__file__.rsplit(".", 1)[0] + ".py")
        common_object_test(domain)

    def test_config_from_object(self):
        domain = Domain(__name__)
        domain.config.from_object(__name__)
        common_object_test(domain)

    def test_config_from_json(self):
        domain = Domain(__name__)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        domain.config.from_json(os.path.join(current_dir, "config.json"))
        common_object_test(domain)

    def test_config_from_mapping(self):
        domain = Domain(__name__)
        domain.config.from_mapping(
            {"SECRET_KEY": "config", "TEST_KEY": "foo", "non_key": "not-a-key"}
        )
        common_object_test(domain)

        domain = Domain(__name__)
        domain.config.from_mapping(
            [("SECRET_KEY", "config"), ("TEST_KEY", "foo"), ("non_key", "not-a-key")]
        )
        common_object_test(domain)

        domain = Domain(__name__)
        domain.config.from_mapping(
            SECRET_KEY="config", TEST_KEY="foo", non_key="not-a-key"
        )
        common_object_test(domain)

        domain = Domain(__name__)
        with pytest.raises(TypeError):
            domain.config.from_mapping({}, {})

    def test_config_from_class(self):
        class Base(object):
            TEST_KEY = "foo"

        class Test(Base):
            SECRET_KEY = "config"

        domain = Domain(__name__)
        domain.config.from_object(Test)
        common_object_test(domain)

    def test_config_from_envvar(self):
        env = os.environ
        try:
            os.environ = {}
            domain = Domain(__name__)
            with pytest.raises(RuntimeError) as e:
                domain.config.from_envvar("FOO_SETTINGS")
            assert "'FOO_SETTINGS' is not set" in str(e.value)
            assert not domain.config.from_envvar("FOO_SETTINGS", silent=True)

            os.environ = {"FOO_SETTINGS": __file__.rsplit(".", 1)[0] + ".py"}
            assert domain.config.from_envvar("FOO_SETTINGS")
            common_object_test(domain)
        finally:
            os.environ = env

    def test_config_from_envvar_missing(self):
        env = os.environ
        try:
            os.environ = {"FOO_SETTINGS": "missing.cfg"}
            with pytest.raises(IOError) as e:
                domain = Domain(__name__)
                domain.config.from_envvar("FOO_SETTINGS")
            msg = str(e.value)
            assert msg.startswith(
                "[Errno 2] Unable to load configuration "
                "file (No such file or directory):",
            )
            assert msg.endswith("missing.cfg'")
            assert not domain.config.from_envvar("FOO_SETTINGS", silent=True)
        finally:
            os.environ = env

    def test_config_missing(self):
        domain = Domain(__name__)
        with pytest.raises(IOError) as e:
            domain.config.from_pyfile("missing.cfg")
        msg = str(e.value)
        assert msg.startswith(
            "[Errno 2] Unable to load configuration "
            "file (No such file or directory):",
        )
        assert msg.endswith("missing.cfg'")
        assert not domain.config.from_pyfile("missing.cfg", silent=True)

    def test_config_missing_json(self):
        domain = Domain(__name__)
        with pytest.raises(IOError) as e:
            domain.config.from_json("missing.json")
        msg = str(e.value)
        assert msg.startswith(
            "[Errno 2] Unable to load configuration "
            "file (No such file or directory):",
        )
        assert msg.endswith("missing.json'")
        assert not domain.config.from_json("missing.json", silent=True)

    def test_custom_config_class(self):
        class SubConfig(Config):
            pass

        class SubDomain(Domain):
            config_class = SubConfig

        domain = SubDomain(__name__)
        assert isinstance(domain.config, SubConfig)
        domain.config.from_object(__name__)
        common_object_test(domain)

    def test_get_namespace(self):
        domain = Domain(__name__)
        domain.config["FOO_OPTION_1"] = "foo option 1"
        domain.config["FOO_OPTION_2"] = "foo option 2"
        domain.config["BAR_STUFF_1"] = "bar stuff 1"
        domain.config["BAR_STUFF_2"] = "bar stuff 2"
        foo_options = domain.config.get_namespace("FOO_")
        assert 2 == len(foo_options)
        assert "foo option 1" == foo_options["option_1"]
        assert "foo option 2" == foo_options["option_2"]
        bar_options = domain.config.get_namespace("BAR_", lowercase=False)
        assert 2 == len(bar_options)
        assert "bar stuff 1" == bar_options["STUFF_1"]
        assert "bar stuff 2" == bar_options["STUFF_2"]
        foo_options = domain.config.get_namespace("FOO_", trim_namespace=False)
        assert 2 == len(foo_options)
        assert "foo option 1" == foo_options["foo_option_1"]
        assert "foo option 2" == foo_options["foo_option_2"]
        bar_options = domain.config.get_namespace(
            "BAR_", lowercase=False, trim_namespace=False,
        )
        assert 2 == len(bar_options)
        assert "bar stuff 1" == bar_options["BAR_STUFF_1"]
        assert "bar stuff 2" == bar_options["BAR_STUFF_2"]
