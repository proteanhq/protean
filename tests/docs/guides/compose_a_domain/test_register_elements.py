"""The examples on the Register Elements guide behave as the page says."""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_decorator_registers_the_aggregate():
    example = load_example("guides/compose-a-domain/002.py")
    example.domain.init(traverse=False)

    assert example.domain.registry.elements == {"aggregates": [example.User]}
    assert example.User.meta_.stream_category == (
        f"{example.domain.normalized_name}::user"
    )


def test_decorator_options_set_the_stream_category():
    example = load_example("guides/compose-a-domain/015.py")
    example.domain.init(traverse=False)

    assert example.domain.registry.elements == {"aggregates": [example.User]}
    assert example.User.meta_.stream_category == (
        f"{example.domain.normalized_name}::account"
    )


def test_manual_registration_registers_the_aggregate_with_options():
    example = load_example("guides/compose-a-domain/014.py")
    example.domain.init(traverse=False)

    assert example.domain.registry.elements == {"aggregates": [example.User]}
    assert example.User.meta_.stream_category == (
        f"{example.domain.normalized_name}::account"
    )
