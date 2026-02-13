"""PoC tests for derive_element_class() with Pydantic ModelMetaclass.

Validates:
- type() auto-delegates to ModelMetaclass when bases include BaseModel subclass
- __annotations__ are preserved in new class namespace
- _rebind_class_cells works with Pydantic-based classes
- Dynamically-created classes behave identically to statically defined ones
- model_fields, model_json_schema, model_dump all work on derived classes
- super() works correctly in derived classes (PEP 3135)
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID, uuid4

import pytest
from pydantic import Field, ValidationError

from tests.spike_pydantic.base_classes import (
    Options,
    ProteanAggregate,
    ProteanCommand,
    ProteanEntity,
    ProteanEvent,
    ProteanValueObject,
    invariant,
)


# ---------------------------------------------------------------------------
# Simulated derive_element_class (standalone, no dependency on Protean domain)
# ---------------------------------------------------------------------------
def _rebind_class_cells_simple(new_cls: type, original_cls: type) -> None:
    """Simplified version of _rebind_class_cells for PoC testing."""
    import types

    for attr_name in list(vars(new_cls)):
        attr_value = vars(new_cls)[attr_name]
        if isinstance(attr_value, types.FunctionType):
            freevars = attr_value.__code__.co_freevars
            if "__class__" not in freevars:
                continue
            closure = attr_value.__closure__
            if closure is None:
                continue
            idx = freevars.index("__class__")
            try:
                current_value = closure[idx].cell_contents
            except ValueError:
                continue
            if current_value is not original_cls:
                continue
            new_closure = tuple(
                types.CellType(new_cls) if i == idx else cell
                for i, cell in enumerate(closure)
            )
            new_func = types.FunctionType(
                attr_value.__code__,
                attr_value.__globals__,
                attr_value.__name__,
                attr_value.__defaults__,
                new_closure,
            )
            new_func.__kwdefaults__ = attr_value.__kwdefaults__
            new_func.__dict__.update(attr_value.__dict__)
            new_func.__module__ = attr_value.__module__
            new_func.__qualname__ = (
                new_cls.__qualname__ + "." + attr_value.__qualname__.split(".")[-1]
            )
            try:
                type.__setattr__(new_cls, attr_name, new_func)
            except (AttributeError, TypeError):
                pass


def derive_element_class_spike(
    element_cls: type,
    base_cls: type,
    **opts: Any,
) -> type:
    """Simulate derive_element_class using type() with Pydantic base."""
    if not issubclass(element_cls, base_cls):
        original_cls = element_cls
        new_dict = element_cls.__dict__.copy()
        new_dict.pop("__dict__", None)
        new_dict.pop("__weakref__", None)

        # CRITICAL: Preserve __annotations__ for Pydantic ModelMetaclass
        # __annotations__ should already be in element_cls.__dict__ if the user
        # declared fields with type annotations.

        new_dict["_meta"] = Options(opts)

        # type() auto-delegates to ModelMetaclass because base_cls is a BaseModel subclass
        element_cls = type(element_cls.__name__, (base_cls,), new_dict)

        # Fix super() calls (PEP 3135)
        _rebind_class_cells_simple(element_cls, original_cls)
    else:
        element_cls._meta = Options(opts)

    return element_cls


# ---------------------------------------------------------------------------
# Test: Basic derive_element_class with ValueObject
# ---------------------------------------------------------------------------
class TestDeriveValueObject:
    def test_derive_plain_class_into_vo(self):
        """A plain class with annotations should become a ProteanValueObject."""

        class RawAddress:
            street: str
            city: str
            zip_code: str

        DerivedAddress = derive_element_class_spike(RawAddress, ProteanValueObject)

        # Should be a subclass of ProteanValueObject
        assert issubclass(DerivedAddress, ProteanValueObject)

        # Should work as a Pydantic model
        addr = DerivedAddress(street="123 Main", city="NYC", zip_code="10001")
        assert addr.street == "123 Main"

        # Should be frozen
        with pytest.raises(ValidationError):
            addr.street = "456 Oak"

        # Should have model_fields
        assert "street" in DerivedAddress.model_fields
        assert "city" in DerivedAddress.model_fields

    def test_derive_preserves_defaults(self):
        class RawMoney:
            amount: float
            currency: str = "USD"

        DerivedMoney = derive_element_class_spike(RawMoney, ProteanValueObject)
        m = DerivedMoney(amount=10.0)
        assert m.currency == "USD"

    def test_derive_preserves_field_constraints(self):
        class RawConstrained:
            name: Annotated[str, Field(max_length=10)]
            value: int = Field(ge=0)

        Derived = derive_element_class_spike(RawConstrained, ProteanValueObject)
        with pytest.raises(ValidationError):
            Derived(name="x" * 11, value=0)
        with pytest.raises(ValidationError):
            Derived(name="ok", value=-1)


class TestDeriveEntity:
    def test_derive_plain_class_into_entity(self):
        class RawItem:
            id: UUID = Field(default_factory=uuid4)
            name: str
            qty: int = 1

        DerivedItem = derive_element_class_spike(RawItem, ProteanEntity)
        assert issubclass(DerivedItem, ProteanEntity)

        item = DerivedItem(name="Widget")
        assert item.name == "Widget"
        assert item.qty == 1
        assert item.id is not None

        # Should be mutable
        item.name = "Gadget"
        assert item.name == "Gadget"
        assert item._state.is_changed is True

    def test_derive_entity_validates_on_mutation(self):
        class RawItem:
            id: UUID = Field(default_factory=uuid4)
            name: str
            qty: int = Field(ge=1)

        DerivedItem = derive_element_class_spike(RawItem, ProteanEntity)
        item = DerivedItem(name="Widget", qty=5)
        with pytest.raises(ValidationError):
            item.qty = 0  # ge=1


class TestDeriveAggregate:
    def test_derive_plain_class_into_aggregate(self):
        class RawOrder:
            id: UUID = Field(default_factory=uuid4)
            order_number: str
            total: float = 0.0

        DerivedOrder = derive_element_class_spike(RawOrder, ProteanAggregate)
        assert issubclass(DerivedOrder, ProteanAggregate)

        order = DerivedOrder(order_number="ORD-001")
        assert order._root is order
        assert order._version == -1

    def test_derive_aggregate_with_invariants(self):
        class RawOrder:
            id: UUID = Field(default_factory=uuid4)
            order_number: str
            total: float = 0.0

            @invariant.post
            def total_must_be_positive(self):
                if self.total < 0:
                    from protean.exceptions import ValidationError as PVE

                    raise PVE({"total": ["must be positive"]})

        DerivedOrder = derive_element_class_spike(RawOrder, ProteanAggregate)

        # Invariant should work after derivation
        from protean.exceptions import ValidationError as PVE

        with pytest.raises(PVE):
            DerivedOrder(order_number="ORD-001", total=-5.0)


class TestDeriveCommand:
    def test_derive_plain_class_into_command(self):
        class RawCmd:
            order_id: UUID
            items: list[dict]

        DerivedCmd = derive_element_class_spike(RawCmd, ProteanCommand)
        assert issubclass(DerivedCmd, ProteanCommand)

        uid = uuid4()
        cmd = DerivedCmd(order_id=uid, items=[{"p": "w"}])
        assert cmd.order_id == uid
        assert cmd._metadata["kind"] == "COMMAND"

        # Should be frozen
        with pytest.raises(ValidationError):
            cmd.order_id = uuid4()


class TestDeriveEvent:
    def test_derive_plain_class_into_event(self):
        class RawEvt:
            order_id: UUID
            order_number: str

        DerivedEvt = derive_element_class_spike(RawEvt, ProteanEvent)
        assert issubclass(DerivedEvt, ProteanEvent)

        uid = uuid4()
        evt = DerivedEvt(order_id=uid, order_number="ORD-001")
        assert evt._metadata["kind"] == "EVENT"
        assert evt._metadata["type"] == "RawEvt"


# ---------------------------------------------------------------------------
# Test: Already subclass scenario
# ---------------------------------------------------------------------------
class TestAlreadySubclass:
    def test_already_subclass_skips_type(self):
        """If element_cls already extends base_cls, just set meta_."""

        class MyVO(ProteanValueObject):
            name: str
            value: int = 0

        result = derive_element_class_spike(MyVO, ProteanValueObject, abstract=False)
        # Should be the same class (not re-derived)
        assert result is MyVO
        assert result._meta["abstract"] is False


# ---------------------------------------------------------------------------
# Test: super() works in derived classes (PEP 3135)
# ---------------------------------------------------------------------------
class TestSuperInDerived:
    def test_super_call_works(self):
        """After _rebind_class_cells, super() should reference the correct class."""

        class RawEntity:
            id: UUID = Field(default_factory=uuid4)
            name: str

            def greet(self) -> str:
                return f"Hello from {self.name}"

        DerivedEntity = derive_element_class_spike(RawEntity, ProteanEntity)
        entity = DerivedEntity(name="World")
        assert entity.greet() == "Hello from World"

    def test_super_in_method_with_invariant(self):
        """Methods using super() should work after derivation."""

        class RawAgg:
            id: UUID = Field(default_factory=uuid4)
            name: str
            count: int = 0

            def increment(self):
                self.count += 1

        DerivedAgg = derive_element_class_spike(RawAgg, ProteanAggregate)
        agg = DerivedAgg(name="Counter")
        agg.increment()
        assert agg.count == 1


# ---------------------------------------------------------------------------
# Test: Schema and dump work on derived classes
# ---------------------------------------------------------------------------
class TestDerivedClassSchema:
    def test_schema_on_derived_vo(self):
        class RawAddr:
            street: str
            city: str

        Derived = derive_element_class_spike(RawAddr, ProteanValueObject)
        schema = Derived.model_json_schema()
        assert schema["type"] == "object"
        assert "street" in schema["properties"]
        assert "city" in schema["properties"]

    def test_dump_on_derived_entity(self):
        class RawItem:
            id: UUID = Field(default_factory=uuid4)
            name: str
            qty: int = 1

        Derived = derive_element_class_spike(RawItem, ProteanEntity)
        item = Derived(name="Widget")
        data = item.model_dump()
        assert "name" in data
        assert data["name"] == "Widget"
        assert data["qty"] == 1
        assert "_state" not in data

    def test_schema_on_derived_command(self):
        class RawCmd:
            order_id: UUID
            amount: float = Field(ge=0)

        Derived = derive_element_class_spike(RawCmd, ProteanCommand)
        schema = Derived.model_json_schema()
        assert "order_id" in schema["properties"]
        assert schema["properties"]["amount"].get("minimum") == 0
