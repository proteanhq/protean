import json
import os
import textwrap

import pytest

import protean

# config keys used for the TestConfig
TEST_KEY = "foo"
SECRET_KEY = "config"


def config_test(domain):
    assert domain.secret_key == "config"
    assert domain.config["TEST_KEY"] == "foo"
    assert "TestConfig" not in domain.config


def test_config_from_pyfile():
    domain = protean.Domain(__name__)
    domain.config.from_pyfile(f"{__file__.rsplit('.', 1)[0]}.py")
    config_test(domain)


def test_config_from_object():
    domain = protean.Domain(__name__)
    domain.config.from_object(__name__)
    config_test(domain)


def test_config_from_file():
    domain = protean.Domain(__name__)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    domain.config.from_file(
        os.path.join(current_dir, "support", "config.json"), json.load
    )
    config_test(domain)


def test_config_from_mapping():
    domain = protean.Domain(__name__)
    domain.config.from_mapping({"SECRET_KEY": "config", "TEST_KEY": "foo"})
    config_test(domain)

    domain = protean.Domain(__name__)
    domain.config.from_mapping([("SECRET_KEY", "config"), ("TEST_KEY", "foo")])
    config_test(domain)

    domain = protean.Domain(__name__)
    domain.config.from_mapping(SECRET_KEY="config", TEST_KEY="foo")
    config_test(domain)

    domain = protean.Domain(__name__)
    with pytest.raises(TypeError):
        domain.config.from_mapping({}, {})


def test_config_from_class():
    class Base:
        TEST_KEY = "foo"

    class Test(Base):
        SECRET_KEY = "config"

    domain = protean.Domain(__name__)
    domain.config.from_object(Test)
    config_test(domain)


def test_config_from_envvar(monkeypatch):
    monkeypatch.setattr("os.environ", {})
    domain = protean.Domain(__name__)
    with pytest.raises(RuntimeError) as e:
        domain.config.from_envvar("FOO_SETTINGS")
        assert "'FOO_SETTINGS' is not set" in str(e.value)
    assert not domain.config.from_envvar("FOO_SETTINGS", silent=True)

    monkeypatch.setattr(
        "os.environ", {"FOO_SETTINGS": f"{__file__.rsplit('.', 1)[0]}.py"}
    )
    assert domain.config.from_envvar("FOO_SETTINGS")
    config_test(domain)


def test_config_from_envvar_missing(monkeypatch):
    monkeypatch.setattr("os.environ", {"FOO_SETTINGS": "missing.cfg"})
    with pytest.raises(IOError) as e:
        domain = protean.Domain(__name__)
        domain.config.from_envvar("FOO_SETTINGS")
    msg = str(e.value)
    assert msg.startswith(
        "[Errno 2] Unable to load configuration file (No such file or directory):"
    )
    assert msg.endswith("missing.cfg'")
    assert not domain.config.from_envvar("FOO_SETTINGS", silent=True)


def test_config_missing():
    domain = protean.Domain(__name__)
    with pytest.raises(IOError) as e:
        domain.config.from_pyfile("missing.cfg")
    msg = str(e.value)
    assert msg.startswith(
        "[Errno 2] Unable to load configuration file (No such file or directory):"
    )
    assert msg.endswith("missing.cfg'")
    assert not domain.config.from_pyfile("missing.cfg", silent=True)


def test_config_missing_file():
    domain = protean.Domain(__name__)
    with pytest.raises(IOError) as e:
        domain.config.from_file("missing.json", load=json.load)
    msg = str(e.value)
    assert msg.startswith(
        "[Errno 2] Unable to load configuration file (No such file or directory):"
    )
    assert msg.endswith("missing.json'")
    assert not domain.config.from_file("missing.json", load=json.load, silent=True)


def test_custom_config_class():
    class Config(protean.Config):
        pass

    class Domain(protean.Domain):
        config_class = Config

    domain = Domain(__name__)
    assert isinstance(domain.config, Config)
    domain.config.from_object(__name__)
    config_test(domain)


def test_get_namespace():
    domain = protean.Domain(__name__)
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
        "BAR_", lowercase=False, trim_namespace=False
    )
    assert 2 == len(bar_options)
    assert "bar stuff 1" == bar_options["BAR_STUFF_1"]
    assert "bar stuff 2" == bar_options["BAR_STUFF_2"]


@pytest.mark.parametrize("encoding", ["utf-8", "iso-8859-15", "latin-1"])
def test_from_pyfile_weird_encoding(tmpdir, encoding):
    f = tmpdir.join("my_config.py")
    f.write_binary(
        textwrap.dedent(
            f"""
            # -*- coding: {encoding} -*-
            TEST_VALUE = "föö"
            """
        ).encode(encoding)
    )
    domain = protean.Domain(__name__)
    domain.config.from_pyfile(str(f))
    value = domain.config["TEST_VALUE"]
    assert value == "föö"
