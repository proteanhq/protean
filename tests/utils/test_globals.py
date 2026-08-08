"""Tests for the stdlib ``contextvars``-backed context locals.

These tests pin the push/pop nesting semantics of ``current_domain``,
``current_uow``, and ``g``, and verify that the active context follows the
execution context across async boundaries.
"""

import asyncio
import warnings
from concurrent.futures import ThreadPoolExecutor

import pytest

from protean import Domain, UnitOfWork
from protean.utils.globals import (
    _domain_context_stack,
    _uow_context_stack,
    current_domain,
    current_uow,
    g,
)


@pytest.fixture
def fresh_domain():
    """A separate, initialized domain for context-local tests."""
    domain = Domain(name="GlobalsTest")
    domain._initialize()
    return domain


def _drain_stack(stack) -> None:
    while stack.pop() is not None:
        pass


@pytest.fixture(autouse=True)
def _clean_context_stacks():
    """Ensure no-test-domain tests do not leak context state to each other."""
    yield
    _drain_stack(_domain_context_stack)
    _drain_stack(_uow_context_stack)


class TestContextStack:
    """Direct tests for the internal ``_ContextStack``."""

    @pytest.mark.no_test_domain
    def test_push_pop_nesting(self):
        stack = _domain_context_stack
        sentinel_a = object()
        sentinel_b = object()

        assert stack.top is None
        stack.push(sentinel_a)
        assert stack.top is sentinel_a
        stack.push(sentinel_b)
        assert stack.top is sentinel_b
        assert stack.pop() is sentinel_b
        assert stack.top is sentinel_a
        assert stack.pop() is sentinel_a
        assert stack.top is None
        assert stack.pop() is None

    @pytest.mark.no_test_domain
    def test_pop_on_empty_stack_returns_none(self):
        _drain_stack(_domain_context_stack)
        assert _domain_context_stack.pop() is None

    @pytest.mark.no_test_domain
    def test_stack_is_isolated_across_threads(self):
        """A push in one OS thread must not leak to another."""
        stack = _domain_context_stack
        sentinel = object()
        stack.push(sentinel)

        def _check():
            return stack.top

        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(_check).result()

        assert result is None
        assert stack.top is sentinel
        stack.pop()


class TestDomainContextNesting:
    """Nested ``DomainContext`` push/pop behavior."""

    @pytest.mark.no_test_domain
    def test_nested_domain_contexts_resolve_to_innermost(self, fresh_domain):
        domain_a = fresh_domain
        domain_b = Domain(name="InnerDomain")
        domain_b._initialize()

        with domain_a.domain_context():
            assert current_domain == domain_a
            assert isinstance(current_domain, Domain)
            with domain_b.domain_context():
                assert current_domain == domain_b
                assert isinstance(current_domain, Domain)
            assert current_domain == domain_a

    @pytest.mark.no_test_domain
    def test_domain_context_stack_is_independent_of_uow_stack(self, fresh_domain):
        with fresh_domain.domain_context():
            assert _domain_context_stack.top is not None
            assert _uow_context_stack.top is None


class TestUoWContextNesting:
    """Unit-of-Work context stack behavior."""

    @pytest.mark.no_test_domain
    def test_uow_stack_nesting(self, fresh_domain):
        with fresh_domain.domain_context():
            outer = UnitOfWork()
            outer.start()
            assert current_uow == outer
            assert _uow_context_stack.top is outer

            inner = UnitOfWork()
            inner.start()  # joins outer, does not push
            assert current_uow == outer
            assert _uow_context_stack.top is outer

            inner.commit()  # no-op for nested participant
            assert current_uow == outer

            outer.commit()
            assert _uow_context_stack.top is None

    @pytest.mark.no_test_domain
    def test_uow_pops_itself_on_commit(self, fresh_domain):
        with fresh_domain.domain_context():
            uow = UnitOfWork()
            uow.start()
            assert _uow_context_stack.top is uow
            uow.commit()
            assert _uow_context_stack.top is None

    @pytest.mark.no_test_domain
    def test_uow_stack_is_isolated_across_threads(self, fresh_domain):
        """A UoW started in one OS thread must not leak to another."""
        with fresh_domain.domain_context():
            uow = UnitOfWork()
            uow.start()

            def _check():
                return _uow_context_stack.top

            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(_check).result()

            assert result is None
            assert current_uow == uow
            uow.commit()


class TestAsyncPropagation:
    """The active context follows the execution context across ``await``."""

    @pytest.mark.no_test_domain
    def test_current_domain_propagates_across_await(self, fresh_domain):
        async def _inside():
            await asyncio.sleep(0)
            assert current_domain == fresh_domain

        async def _main():
            with fresh_domain.domain_context():
                await _inside()

        asyncio.run(_main())

    @pytest.mark.no_test_domain
    def test_current_domain_propagates_to_task(self, fresh_domain):
        async def _task():
            await asyncio.sleep(0)
            assert current_domain == fresh_domain

        async def _main():
            with fresh_domain.domain_context():
                await asyncio.create_task(_task())

        asyncio.run(_main())

    @pytest.mark.no_test_domain
    def test_current_uow_propagates_across_await(self, fresh_domain):
        async def _inside():
            await asyncio.sleep(0)
            assert current_uow is not None

        async def _main():
            with fresh_domain.domain_context():
                uow = UnitOfWork()
                uow.start()
                await _inside()
                uow.commit()

        asyncio.run(_main())

    @pytest.mark.no_test_domain
    def test_concurrent_async_tasks_keep_domains_isolated(self, fresh_domain):
        # Two tasks running concurrently on the same OS thread must see their
        # own current_domain, not whichever context was pushed last. The stdlib
        # contextvars backing guarantees this without thread-local machinery.
        other_domain = Domain(name="Other")

        async def _in_domain(domain, expected_name):
            with domain.domain_context():
                await asyncio.sleep(0)
                assert current_domain.name == expected_name
                await asyncio.sleep(0)
                assert current_domain.name == expected_name

        async def _main():
            await asyncio.gather(
                _in_domain(fresh_domain, "GlobalsTest"),
                _in_domain(other_domain, "Other"),
            )

        asyncio.run(_main())


class TestProxyBehavior:
    """Behavioral contract of the request-scoped proxies."""

    @pytest.mark.no_test_domain
    def test_current_domain_is_falsy_outside_context(self):
        assert bool(current_domain) is False

    @pytest.mark.no_test_domain
    def test_current_domain_warns_on_access_outside_context(self):
        # Resolving the proxy (truthiness, repr, or attribute access) triggers
        # the lookup and therefore the warning. The warning must appear to come
        # from user code, not from inside protean.utils.globals.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            bool(current_domain)
        assert len(caught) == 1
        assert "Working outside of domain context" in str(caught[0].message)
        assert "protean/utils/globals.py" not in caught[0].filename

    @pytest.mark.no_test_domain
    def test_current_domain_attribute_access_outside_context_raises(self):
        with pytest.raises(AttributeError):
            _ = current_domain.config

    @pytest.mark.no_test_domain
    def test_current_uow_is_falsy_outside_context(self):
        assert bool(current_uow) is False

    @pytest.mark.no_test_domain
    def test_g_set_get_delete_attribute(self, fresh_domain):
        with fresh_domain.domain_context():
            g.trace_id = "abc"
            assert g.trace_id == "abc"
            assert getattr(g, "trace_id") == "abc"
            del g.trace_id
            with pytest.raises(AttributeError):
                _ = g.trace_id

    @pytest.mark.no_test_domain
    def test_g_contains_and_iterates(self, fresh_domain):
        with fresh_domain.domain_context():
            g.a = 1
            g.b = 2
            assert "a" in g
            assert "z" not in g
            assert set(g) == {"a", "b"}

    @pytest.mark.no_test_domain
    def test_g_attribute_access_outside_context_raises(self):
        with pytest.raises(AttributeError):
            _ = g.missing

    @pytest.mark.no_test_domain
    def test_g_repr_inside_context(self, fresh_domain):
        with fresh_domain.domain_context():
            assert "GlobalsTest" in repr(g)

    @pytest.mark.no_test_domain
    def test_proxy_str_and_dir_outside_context(self):
        assert str(current_domain) == "None"
        assert "__class__" in dir(current_domain)

    @pytest.mark.no_test_domain
    def test_proxy_str_delegates_inside_context(self, fresh_domain):
        with fresh_domain.domain_context():
            assert "GlobalsTest" in str(current_domain)

    @pytest.mark.no_test_domain
    def test_proxy_hash_outside_context(self):
        assert hash(current_domain) == hash(None)

    @pytest.mark.no_test_domain
    def test_proxy_dir_delegates(self, fresh_domain):
        with fresh_domain.domain_context():
            names = dir(current_domain)
            assert "config" in names
            assert "repository_for" in names

    @pytest.mark.no_test_domain
    def test_proxy_eq_and_hash_delegates(self, fresh_domain):
        with fresh_domain.domain_context():
            assert current_domain == fresh_domain
            assert hash(current_domain) == hash(fresh_domain)
            assert current_domain is not fresh_domain
            assert current_domain != None  # noqa: E711

    @pytest.mark.no_test_domain
    def test_proxy_eq_when_unbound(self):
        # The proxy object itself is always present; only its resolved value is None.
        assert current_domain is not None
        assert current_domain is current_domain
        assert current_domain == None  # noqa: E711
        assert current_domain != object()

    @pytest.mark.no_test_domain
    def test_proxy_contains_and_iter_raise_when_unbound(self):
        with pytest.raises(TypeError):
            "x" in current_domain  # noqa: B015
        with pytest.raises(TypeError):
            list(current_domain)


class TestDomainContextWarning:
    """Warning behavior outside an active domain context."""

    @pytest.mark.no_test_domain
    def test_each_access_outside_context_warns(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            bool(current_domain)
            repr(current_domain)
        assert len(caught) == 2
        assert all(
            "Working outside of domain context" in str(w.message) for w in caught
        )
