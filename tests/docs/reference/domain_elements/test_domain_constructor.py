"""The examples on the Domain constructor reference behave as the page says."""

import re

import pytest

from protean.fields import String
from tests.docs.support import DOCS_SRC, load_example

pytestmark = pytest.mark.no_test_domain

EXAMPLES = DOCS_SRC / "reference" / "domain-elements" / "domain-constructor"


def test_all_none_arguments_fall_back_to_the_defaults(monkeypatch):
    monkeypatch.delenv("DOMAIN_ROOT_PATH", raising=False)
    example = load_example("reference/domain-elements/domain-constructor/001.py")

    assert example.domain.name == example.__name__
    assert example.domain.root_path == str(EXAMPLES.resolve())


def test_explicit_root_path_is_used_as_given(monkeypatch):
    monkeypatch.setenv("DOMAIN_ROOT_PATH", "/from/the/environment")
    example = load_example("reference/domain-elements/domain-constructor/002.py")

    assert example.domain.root_path == "/path/to/domain"


def test_root_path_comes_from_the_environment_variable(monkeypatch):
    monkeypatch.setenv("DOMAIN_ROOT_PATH", "/path/to/domain")
    example = load_example("reference/domain-elements/domain-constructor/003.py")

    assert example.domain.root_path == "/path/to/domain"


def test_root_path_is_the_folder_of_the_calling_file(monkeypatch):
    monkeypatch.delenv("DOMAIN_ROOT_PATH", raising=False)
    example = load_example("reference/domain-elements/domain-constructor/004.py")

    assert example.domain.root_path == str(EXAMPLES.resolve())


def test_explicit_name_is_the_domain_name():
    example = load_example("reference/domain-elements/domain-constructor/005.py")

    assert example.domain.name == "ecommerce"


def test_default_name_is_the_module_name():
    example = load_example("reference/domain-elements/domain-constructor/006.py")

    assert example.domain.name == example.__name__
    assert (
        example.domain.name
        == "docs_src_reference_domain_elements_domain_constructor_006"
    )


def test_identity_function_generates_the_identities():
    example = load_example("reference/domain-elements/domain-constructor/007.py")

    @example.domain.aggregate
    class Customer:
        name: String()

    example.domain.init(traverse=False)

    assert example.domain.config["identity_strategy"] == "function"
    with example.domain.domain_context():
        first = Customer(name="Jane")
        second = Customer(name="John")

    assert re.fullmatch(r"custom-id-\d{4}", first.id)
    assert re.fullmatch(r"custom-id-\d{4}", second.id)


def test_config_overrides_the_default_configuration(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    example = load_example("reference/domain-elements/domain-constructor/008.py")

    assert example.domain.config["identity_strategy"] == "uuid"
    assert example.domain.config["databases"]["default"] == {
        "provider": "postgresql",
        "database_uri": "postgresql://user:pass@localhost/db",
    }
