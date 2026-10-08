"""The examples on the Activate the domain guide behave as the page says."""

import pytest

from protean import current_domain, g
from protean.domain.context import has_domain_context
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_domain_is_current_only_inside_the_context_manager():
    example = load_example("guides/compose-a-domain/018.py")

    assert example.user_repo.meta_.part_of is example.User
    assert not has_domain_context()

    with example.domain.domain_context():
        assert current_domain._get_current_object() is example.domain

    assert not has_domain_context()
    with pytest.warns(UserWarning, match="Working outside of domain context"):
        assert current_domain._get_current_object() is None


def test_manual_push_and_pop_activate_then_reset_the_domain():
    example = load_example("guides/compose-a-domain/activate-domain/001.py")

    assert example.user_repo.meta_.part_of is example.User
    assert example.context.domain is example.domain
    assert not has_domain_context()

    example.context.push()
    try:
        assert current_domain._get_current_object() is example.domain
    finally:
        example.context.pop()
    assert not has_domain_context()


def test_get_log_returns_one_file_per_context_and_teardown_closes_it():
    example = load_example("guides/compose-a-domain/activate-domain/002.py")

    with example.domain.domain_context():
        log = example.get_log()
        assert example.get_log() is log
        assert g.log is log
        assert not log.closed

    assert log.closed

    with example.domain.domain_context():
        assert "log" not in g
        assert example.get_log() is not log


def test_teardown_is_safe_when_no_log_was_opened():
    example = load_example("guides/compose-a-domain/activate-domain/002.py")

    with example.domain.domain_context():
        assert "log" not in g

    assert example.teardown_log_file in (
        example.domain.teardown_domain_context_functions
    )
