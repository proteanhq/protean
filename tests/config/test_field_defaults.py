"""Tests for the ``[field_defaults]`` config section.

``[field_defaults] sanitize`` sets the domain-level default for String/Text
fields declared without an explicit ``sanitize=`` kwarg. These tests cover the
config plumbing (the default value, the key filter, deep-merge, and
per-environment override); the field behavior it drives lives in
``tests/field/test_string.py``.
"""

import pytest

from protean import Domain
from protean.domain.config import Config2, _default_config
from protean.exceptions import ConfigurationError

# These tests build their own Domain and Config2 objects, so the suite's autouse
# ``test_domain`` fixture has nothing to contribute and would only initialize an
# unrelated domain for every case.
pytestmark = pytest.mark.no_test_domain


def test_default_config_has_field_defaults_sanitize_false():
    assert _default_config()["field_defaults"]["sanitize"] is False


def test_load_from_dict_accepts_a_sanitize_override():
    config = Config2.load_from_dict({"field_defaults": {"sanitize": True}})
    assert config["field_defaults"]["sanitize"] is True


def test_partial_override_deep_merges_with_the_default():
    # A user config that names only field_defaults still deep-merges, so the
    # section survives and the sanitize key is applied.
    config = Config2.load_from_dict({"field_defaults": {"sanitize": True}})
    assert config["field_defaults"] == {"sanitize": True}


def test_unrelated_config_keeps_the_default():
    config = Config2.load_from_dict({"debug": True})
    assert config["field_defaults"]["sanitize"] is False


def test_per_environment_override_merges(monkeypatch):
    monkeypatch.setenv("PROTEAN_ENV", "prod")
    config = Config2._normalize_config(
        {
            "field_defaults": {"sanitize": False},
            "prod": {"field_defaults": {"sanitize": True}},
        }
    )
    assert config["field_defaults"]["sanitize"] is True


def test_domain_init_exposes_the_key():
    domain = Domain(name="FD", config={"field_defaults": {"sanitize": True}})
    domain.init(traverse=False)
    assert domain.config["field_defaults"]["sanitize"] is True


def test_domain_init_defaults_the_key_when_absent():
    domain = Domain(name="FD")
    domain.init(traverse=False)
    assert domain.config["field_defaults"]["sanitize"] is False


class TestLoadingFromATomlFile:
    """The documented way to set this is a `[field_defaults]` table in
    `domain.toml`, so the TOML path is covered end to end: a spelling or
    bootstrap-path regression would otherwise leave the documented setting inert
    while the dict-based tests above stayed green."""

    def _write(self, tmp_path, body: str) -> str:
        (tmp_path / "domain.toml").write_text(body)
        return str(tmp_path)

    def test_a_toml_table_sets_the_default(self, tmp_path):
        path = self._write(tmp_path, "[field_defaults]\nsanitize = true\n")
        config = Config2.load_from_path(path)
        assert config["field_defaults"]["sanitize"] is True

    def test_a_toml_file_without_the_table_keeps_the_default(self, tmp_path):
        path = self._write(tmp_path, "debug = true\n")
        config = Config2.load_from_path(path)
        assert config["field_defaults"]["sanitize"] is False

    def test_an_env_var_placeholder_resolves_to_its_default(self, tmp_path):
        # Env-var interpolation yields a string, so `sanitize` arrives as
        # `"true"`, not `True`. It is read as the boolean the operator wrote.
        path = self._write(
            tmp_path, '[field_defaults]\nsanitize = "${PROTEAN_SANITIZE|true}"\n'
        )
        config = Config2.load_from_path(path)
        assert config["field_defaults"]["sanitize"] == "true"

    def test_an_env_var_placeholder_reads_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PROTEAN_SANITIZE", "false")
        path = self._write(
            tmp_path, '[field_defaults]\nsanitize = "${PROTEAN_SANITIZE|true}"\n'
        )
        config = Config2.load_from_path(path)
        assert config["field_defaults"]["sanitize"] == "false"

    def test_a_domain_rooted_at_the_file_picks_the_table_up(self, tmp_path):
        path = self._write(tmp_path, "[field_defaults]\nsanitize = true\n")
        domain = Domain(name="FD", root_path=path)
        domain.init(traverse=False)
        assert domain.config["field_defaults"]["sanitize"] is True


class TestMalformedSectionsAreRejected:
    """`field_defaults.sanitize` decides whether unset String/Text fields are
    cleaned. Reading a malformed value as `false` would turn an operator's typo
    into a silent fail-open, so it is rejected when the config loads."""

    def test_a_non_table_section_is_rejected(self):
        with pytest.raises(ConfigurationError) as exc:
            Config2.load_from_dict({"field_defaults": False})
        assert "must be a table" in str(exc.value)

    def test_an_unrecognized_string_is_rejected(self):
        with pytest.raises(ConfigurationError) as exc:
            Config2.load_from_dict({"field_defaults": {"sanitize": "maybe"}})
        assert "field_defaults.sanitize" in str(exc.value)

    def test_a_non_boolean_value_is_rejected(self):
        with pytest.raises(ConfigurationError) as exc:
            Config2.load_from_dict({"field_defaults": {"sanitize": 3}})
        assert "field_defaults.sanitize" in str(exc.value)

    def test_a_recognized_string_spelling_is_accepted(self):
        config = Config2.load_from_dict({"field_defaults": {"sanitize": "ON"}})
        assert config["field_defaults"]["sanitize"] == "ON"

    def test_a_section_without_the_key_is_accepted(self):
        config = Config2.load_from_dict({"field_defaults": {}})
        assert config["field_defaults"]["sanitize"] is False

    def test_a_malformed_toml_value_is_rejected_at_load(self, tmp_path):
        (tmp_path / "domain.toml").write_text('[field_defaults]\nsanitize = "maybe"\n')
        with pytest.raises(ConfigurationError) as exc:
            Config2.load_from_path(str(tmp_path))
        assert "field_defaults.sanitize" in str(exc.value)

    def test_from_object_with_a_dict_is_validated(self):
        # `from_object` is its own bootstrap path, so it gets the same check.
        config = Config2()
        with pytest.raises(ConfigurationError) as exc:
            config.from_object({"field_defaults": {"sanitize": "maybe"}})
        assert "field_defaults.sanitize" in str(exc.value)

    def test_from_object_with_a_class_is_validated(self):
        class Settings:
            FIELD_DEFAULTS = {"sanitize": "maybe"}

        config = Config2()
        with pytest.raises(ConfigurationError) as exc:
            config.from_object(Settings)
        assert "field_defaults.sanitize" in str(exc.value)

    def test_from_object_accepts_a_valid_value(self):
        config = Config2()
        config.from_object({"field_defaults": {"sanitize": True}})
        assert config["field_defaults"]["sanitize"] is True

    def test_a_class_config_without_the_section_is_accepted(self):
        # `from_object` with a plain object copies only uppercase attributes, so
        # a class that names none leaves the section absent entirely.
        class Settings:
            DEBUG = True

        config = Config2()
        config.from_object(Settings)
        assert "field_defaults" not in config

    def test_a_class_config_with_an_empty_section_is_accepted(self):
        # `from_object` on a non-dict does not normalize, so the section stays
        # empty rather than being filled in with the default.
        class Settings:
            FIELD_DEFAULTS: dict = {}

        config = Config2()
        config.from_object(Settings)
        assert config["field_defaults"] == {}
