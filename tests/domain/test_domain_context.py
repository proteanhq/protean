"""Tests for DomainContext and _DomainContextGlobals in domain/context.py."""

import pytest

from protean.domain import Domain
from protean.domain.context import (
    DomainContext,
    _DomainContextGlobals,
    has_domain_context,
)


# ---------------------------------------------------------------------------
# Test: _DomainContextGlobals.__repr__ outside context
# ---------------------------------------------------------------------------
class TestDomainContextGlobalsRepr:
    @pytest.mark.no_test_domain
    def test_repr_outside_context(self):
        """__repr__ falls back to object.__repr__ when no context."""
        g = _DomainContextGlobals()
        result = repr(g)
        assert "protean.g" not in result
        assert "_DomainContextGlobals" in result

    def test_repr_inside_context(self, test_domain):
        """__repr__ shows domain name when in context."""
        g = test_domain.domain_context_globals_class()
        # We are inside test_domain context via conftest
        result = repr(g)
        # The current context belongs to test_domain
        assert "protean.g" in result


# ---------------------------------------------------------------------------
# Test: has_domain_context()
# ---------------------------------------------------------------------------
class TestHasDomainContext:
    def test_has_domain_context_true(self, test_domain):
        """returns True when domain context is active."""
        assert has_domain_context() is True

    @pytest.mark.no_test_domain
    def test_has_domain_context_false(self):
        """returns False when no domain context is active."""
        assert has_domain_context() is False


# ---------------------------------------------------------------------------
# Test: DomainContext.pop() with sentinel
# ---------------------------------------------------------------------------
class TestDomainContextPop:
    def test_pop_with_sentinel_triggers_exc_info(self):
        """pop() without args uses sys.exc_info()[1]."""
        domain = Domain(name="TestPop")
        domain._initialize()
        ctx = domain.domain_context()
        ctx.push()
        # Calling pop() without arguments triggers the _sentinel path
        ctx.pop()

    def test_domain_context_repr(self):
        """DomainContext.__repr__ returns formatted string."""
        domain = Domain(name="ReprTest")
        domain._initialize()
        ctx = DomainContext(domain)
        result = repr(ctx)
        assert "Domain Context" in result
        assert "ReprTest" in result

    def test_domain_context_kwargs(self):
        """DomainContext passes kwargs to globals."""
        domain = Domain(name="KwargsTest")
        domain._initialize()
        ctx = DomainContext(domain, foo="bar", baz=42)
        assert ctx.g.get("foo") == "bar"
        assert ctx.g.get("baz") == 42


# ---------------------------------------------------------------------------
# Test: _DomainContextGlobals methods
# ---------------------------------------------------------------------------
class TestDomainContextGlobalsMethods:
    def test_contains(self):
        """__contains__ checks __dict__."""
        g = _DomainContextGlobals()
        g.key1 = "value1"
        assert "key1" in g
        assert "key2" not in g

    def test_iter(self):
        """__iter__ iterates over __dict__."""
        g = _DomainContextGlobals()
        g.a = 1
        g.b = 2
        keys = list(g)
        assert "a" in keys
        assert "b" in keys

    def test_pop_with_default(self):
        """pop with default returns default."""
        g = _DomainContextGlobals()
        result = g.pop("missing", "default_val")
        assert result == "default_val"

    def test_pop_without_default_raises(self):
        """pop without default raises KeyError."""
        g = _DomainContextGlobals()
        import pytest

        with pytest.raises(KeyError):
            g.pop("missing")

    def test_setdefault(self):
        """setdefault sets and returns default."""
        g = _DomainContextGlobals()
        result = g.setdefault("new_key", "new_val")
        assert result == "new_val"
        assert g.get("new_key") == "new_val"
