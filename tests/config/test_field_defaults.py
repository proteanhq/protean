"""Tests for the ``[field_defaults]`` config section.

``[field_defaults] sanitize`` sets the domain-level default for String/Text
fields declared without an explicit ``sanitize=`` kwarg. These tests cover the
config plumbing (the default value, the key filter, deep-merge, and
per-environment override); the field behavior it drives lives in
``tests/field/test_string.py``.
"""

from protean import Domain
from protean.domain.config import Config2, _default_config


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
