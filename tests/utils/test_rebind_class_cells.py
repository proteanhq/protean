"""Tests for _rebind_class_cells: fixing zero-argument super() after type() recreation.

When derive_element_class creates a new class via type(), methods' __class__
closure cells still reference the original class, breaking zero-argument
super() (PEP 3135).  _rebind_class_cells fixes this.
"""

import types

import pytest

from protean.core.entity import invariant
from protean.domain import Domain
from protean.exceptions import ValidationError
from protean.fields import Identifier, Integer, String
from protean.utils import clone_class
from protean.utils import (
    _fix_function_class_cell,
    _rebuild_function_with_new_class_cell,
    _rebind_class_cells,
)


def _make_domain() -> Domain:
    """Create an isolated domain for testing."""
    return Domain(name="TestSuperFix")


# ---------------------------------------------------------------------------
# Integration tests: domain services through the decorator path
# ---------------------------------------------------------------------------


class TestDomainServiceSuperWithDecorator:
    """Domain services registered via decorator (no explicit inheritance)
    should support zero-argument super() in __init__."""

    def test_super_init_works_with_decorator(self):
        domain = _make_domain()

        @domain.aggregate
        class Order:
            customer_id: Identifier(required=True)

        @domain.aggregate
        class Inventory:
            product_id: Identifier(required=True)
            quantity: Integer()

        @domain.domain_service(part_of=[Order, Inventory])
        class OrderPlacementService:
            def __init__(self, order, inventories):
                super().__init__(order, *inventories)
                self.order = order
                self.inventories = inventories

            def place_order(self):
                return self.order, self.inventories

        domain.init(traverse=False)

        with domain.domain_context():
            order = Order(customer_id="1")
            inv = Inventory(product_id="p1", quantity=10)

            # This would raise TypeError before the fix
            service = OrderPlacementService(order, [inv])
            assert service.order is order
            assert service.inventories == [inv]

    def test_super_init_in_callable_class_with_decorator(self):
        domain = _make_domain()

        @domain.aggregate
        class Order:
            customer_id: Identifier(required=True)

        @domain.aggregate
        class Inventory:
            product_id: Identifier(required=True)
            quantity: Integer()

        @domain.domain_service(part_of=[Order, Inventory])
        class place_order:
            def __init__(self, order, inventories):
                super().__init__(order, *inventories)
                self.order = order
                self.inventories = inventories

            def __call__(self):
                return "placed"

        domain.init(traverse=False)

        with domain.domain_context():
            order = Order(customer_id="1")
            inv = Inventory(product_id="p1", quantity=10)

            service = place_order(order, [inv])
            assert service() == "placed"


class TestInvariantAttributesPreserved:
    """Decorator attributes like _invariant must survive the rebinding."""

    def test_invariant_markers_preserved_after_rebinding(self):
        domain = _make_domain()

        @domain.aggregate
        class Order:
            customer_id: Identifier(required=True)
            payment_id: Identifier()

        @domain.aggregate
        class Inventory:
            product_id: Identifier(required=True)
            quantity: Integer()

        @domain.domain_service(part_of=[Order, Inventory])
        class OrderPlacementService:
            def __init__(self, order, inventories):
                super().__init__(order, *inventories)
                self.order = order
                self.inventories = inventories

            @invariant.pre
            def order_must_have_payment(self):
                if not self.order.payment_id:
                    raise ValidationError(
                        {"_service": ["Order must have a valid payment"]}
                    )

            def place_order(self):
                return "placed"

        domain.init(traverse=False)

        # Invariant should be registered
        assert "order_must_have_payment" in OrderPlacementService._invariants["pre"]

        with domain.domain_context():
            # Invariant should fire
            order = Order(customer_id="1")
            inv = Inventory(product_id="p1", quantity=10)
            service = OrderPlacementService(order, [inv])

            with pytest.raises(ValidationError):
                service.place_order()


class TestMethodsWithoutSuperUnaffected:
    """Methods that don't use super() should be completely unaffected."""

    def test_regular_methods_still_work(self):
        domain = _make_domain()

        @domain.aggregate
        class Agg1:
            name: String()

        @domain.aggregate
        class Agg2:
            name: String()

        @domain.domain_service(part_of=[Agg1, Agg2])
        class SomeService:
            @classmethod
            def do_work(cls, a1, a2):
                return f"{a1.name}-{a2.name}"

        domain.init(traverse=False)

        with domain.domain_context():
            a1 = Agg1(name="hello")
            a2 = Agg2(name="world")
            assert SomeService.do_work(a1, a2) == "hello-world"


class TestCloneClassSuper:
    """clone_class should also preserve super() behavior."""

    def test_cloned_class_super_works(self):
        class Base:
            def greet(self):
                return "base"

        class Child(Base):
            def greet(self):
                return "child+" + super().greet()

        cloned = clone_class(Child, "ClonedChild")
        instance = cloned()
        assert instance.greet() == "child+base"


# ---------------------------------------------------------------------------
# Unit tests: edge cases in the helper functions
# ---------------------------------------------------------------------------


class TestRebuildFunctionEdgeCases:
    """Unit tests for _rebuild_function_with_new_class_cell edge cases."""

    def test_none_func_returns_none(self):
        """Line 127: func is None."""
        assert _rebuild_function_with_new_class_cell(None, object, object) is None

    def test_non_function_returns_none(self):
        """Line 127: func is not a FunctionType."""
        assert (
            _rebuild_function_with_new_class_cell("not a function", object, object)
            is None
        )

    def test_no_class_freevar_returns_none(self):
        """Line 131: __class__ not in co_freevars — regular function."""

        def plain():
            pass

        assert _rebuild_function_with_new_class_cell(plain, object, object) is None

    # Note: The `closure is None` guard (line 135-136 in utils/__init__.py) is
    # defensive code.  CPython never creates a function with `__class__` in
    # co_freevars but no closure, and `__closure__` is a read-only attribute on
    # the immutable `function` type, so it cannot be mocked.

    def test_empty_cell_returns_none(self):
        """Lines 142-144: cell exists but is empty (ValueError on cell_contents)."""
        # Create an empty cell
        empty_cell = types.CellType()

        class Original:
            def method(self):
                return super()

        func = Original.__dict__["method"]
        # Replace closure with one containing an empty cell at the __class__ index
        idx = func.__code__.co_freevars.index("__class__")
        new_closure = list(func.__closure__)
        new_closure[idx] = empty_cell
        synthetic = types.FunctionType(
            func.__code__,
            func.__globals__,
            "synthetic",
            func.__defaults__,
            tuple(new_closure),
        )
        assert (
            _rebuild_function_with_new_class_cell(synthetic, object, Original) is None
        )

    def test_cell_points_to_different_class_returns_none(self):
        """Line 146-147: cell contents is not original_cls."""

        class Original:
            def method(self):
                return super()

        class Unrelated:
            pass

        func = Original.__dict__["method"]
        # original_cls=Unrelated, but cell points to Original → mismatch
        assert _rebuild_function_with_new_class_cell(func, object, Unrelated) is None

    def test_qualname_without_class_prefix(self):
        """Line 175-176: qualname doesn't start with original class prefix."""

        class Original:
            def method(self):
                return super()

        class NewClass:
            pass

        func = Original.__dict__["method"]
        # Manually set qualname to something that doesn't start with Original's qualname
        func.__qualname__ = "some_unrelated_qualname"

        result = _rebuild_function_with_new_class_cell(func, NewClass, Original)
        assert result is not None
        assert result.__qualname__ == "some_unrelated_qualname"


class TestFixFunctionClassCellEdgeCases:
    """Unit tests for _fix_function_class_cell descriptor handling."""

    def test_classmethod_with_super(self):
        """Line 197-198: classmethod with super() gets unwrapped, fixed, re-wrapped."""

        class Original:
            @classmethod
            def cm(cls):
                return super()

        class NewClass:
            pass

        cm_descriptor = Original.__dict__["cm"]
        result = _fix_function_class_cell(cm_descriptor, NewClass, Original)
        assert result is not None
        assert isinstance(result, classmethod)

    def test_staticmethod_without_super_returns_none(self):
        """Line 199: staticmethod without super() returns None."""

        class Original:
            @staticmethod
            def sm():
                return 42

        class NewClass:
            pass

        sm_descriptor = Original.__dict__["sm"]
        result = _fix_function_class_cell(sm_descriptor, NewClass, Original)
        assert result is None

    def test_property_getter_with_super(self):
        """Lines 206-208, 218-219: property getter uses super()."""

        class Base:
            @property
            def val(self):
                return 1

        class Original(Base):
            @property
            def val(self):
                return super().val + 1

        prop = Original.__dict__["val"]
        result = _fix_function_class_cell(prop, type("New", (Base,), {}), Original)
        assert result is not None
        assert isinstance(result, property)

    def test_property_setter_with_super(self):
        """Lines 210-212: property setter uses super()."""

        class Base:
            @property
            def val(self):
                return self._val

            @val.setter
            def val(self, value):
                self._val = value

        class Original(Base):
            @Base.val.setter
            def val(self, value):
                super(Original, self).__init__()  # just to trigger __class__ cell
                self._val = value * 2

        prop = Original.__dict__["val"]
        result = _fix_function_class_cell(prop, type("New", (Base,), {}), Original)
        assert result is not None
        assert isinstance(result, property)

    def test_property_deleter_with_super(self):
        """Lines 214-216: property deleter uses super()."""

        class Base:
            @property
            def val(self):
                return getattr(self, "_val", None)

            @val.deleter
            def val(self):
                self._val = None

        class Original(Base):
            @Base.val.deleter
            def val(self):
                super(Original, self).__init__()  # trigger __class__ cell
                self._val = None

        prop = Original.__dict__["val"]
        result = _fix_function_class_cell(prop, type("New", (Base,), {}), Original)
        assert result is not None
        assert isinstance(result, property)

    def test_property_without_super_returns_none(self):
        """Line 220: property without super() returns None."""

        class Original:
            @property
            def val(self):
                return 42

        result = _fix_function_class_cell(Original.__dict__["val"], object, Original)
        assert result is None

    def test_non_descriptor_returns_none(self):
        """Line 226: non-function, non-descriptor attribute returns None."""
        assert _fix_function_class_cell(42, object, object) is None
        assert _fix_function_class_cell("string", object, object) is None
        assert _fix_function_class_cell([1, 2, 3], object, object) is None


class TestRebindClassCellsEdgeCases:
    """Unit tests for _rebind_class_cells edge cases."""

    def test_type_recreation_with_super_in_classmethod(self):
        """End-to-end: type() recreation with a classmethod using super()."""

        class Base:
            @classmethod
            def greet(cls):
                return "base"

        class Original(Base):
            @classmethod
            def greet(cls):
                return "child+" + super().greet()

        # Recreate via type() like derive_element_class does
        new_dict = Original.__dict__.copy()
        new_dict.pop("__dict__", None)
        NewClass = type("NewClass", (Base,), new_dict)
        _rebind_class_cells(NewClass, Original)

        assert NewClass.greet() == "child+base"

    def test_type_recreation_with_super_in_property(self):
        """End-to-end: type() recreation with a property using super()."""

        class Base:
            @property
            def val(self):
                return 10

        class Original(Base):
            @property
            def val(self):
                return super().val + 5

        new_dict = Original.__dict__.copy()
        new_dict.pop("__dict__", None)
        NewClass = type("NewClass", (Base,), new_dict)
        _rebind_class_cells(NewClass, Original)

        instance = NewClass()
        assert instance.val == 15
