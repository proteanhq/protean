"""Tests for Q objects and the Node tree graph in utils/query.py."""

import copy

import pytest

from protean import Q
from protean.utils.query import Node, RegisterLookupMixin


# ---------------------------------------------------------------------------
# Tests: Q deconstruct / reconstruct
# ---------------------------------------------------------------------------
class TestQ:
    """Class that holds tests for Q Objects"""

    def test_deconstruct(self):
        q = Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert path == "protean.utils.query.Q"
        assert args == ()
        assert kwargs == {"price__gt": 10.0}

    def test_deconstruct_negated(self):
        q = ~Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert args == ()
        assert kwargs == {
            "price__gt": 10.0,
            "_negated": True,
        }

    def test_deconstruct_or(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q3 = q1 | q2
        path, args, kwargs = q3.deconstruct()
        assert args == (
            ("price__gt", 10.0),
            ("price", 11.0),
        )
        assert kwargs == {"_connector": "OR"}

    def test_deconstruct_and(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q = q1 & q2
        path, args, kwargs = q.deconstruct()
        assert args == (
            ("price__gt", 10.0),
            ("price", 11.0),
        )
        assert kwargs == {}

    def test_deconstruct_multiple_kwargs(self):
        q = Q(price__gt=10.0, price=11.0)
        path, args, kwargs = q.deconstruct()
        assert args == (
            ("price", 11.0),
            ("price__gt", 10.0),
        )
        assert kwargs == {}

    def test_reconstruct(self):
        q = Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q

    def test_reconstruct_negated(self):
        q = ~Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q

    def test_reconstruct_or(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q = q1 | q2
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q

    def test_reconstruct_and(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q = q1 & q2
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q

    def test_deconstruct_single_child(self):
        """deconstruct with single non-Q child."""
        q = Q(name="Alice")
        path, args, kwargs = q.deconstruct()
        assert args == ()
        assert kwargs == {"name": "Alice"}
        assert "Q" in path

    def test_deconstruct_multiple_children(self):
        """deconstruct with multiple children."""
        q = Q(name="Alice", age=30)
        path, args, kwargs = q.deconstruct()
        assert len(args) == 2  # Two sorted children
        assert kwargs == {}

    def test_deconstruct_non_default_connector(self):
        """deconstruct includes connector if non-default."""
        q1 = Q(name="Alice")
        q2 = Q(age=30)
        q = q1 | q2
        path, args, kwargs = q.deconstruct()
        assert kwargs.get("_connector") == Q.OR

    def test_deconstruct_negated_flag(self):
        """deconstruct includes _negated=True when negated."""
        q = ~Q(name="Alice")
        path, args, kwargs = q.deconstruct()
        assert kwargs.get("_negated") is True


# ---------------------------------------------------------------------------
# Tests: RegisterLookupMixin._delist_lookup
# ---------------------------------------------------------------------------
class TestDelistLookup:
    def test_delist_lookup_by_name(self):
        """_delist_lookup removes a lookup from class_lookups."""

        class FakeLookup:
            lookup_name = "test_lookup"

        class MyMixin(RegisterLookupMixin):
            pass

        MyMixin.register_lookup(FakeLookup)
        assert "test_lookup" in MyMixin.get_lookups()

        MyMixin._delist_lookup(FakeLookup)
        MyMixin._clear_cached_lookups()
        assert "test_lookup" not in MyMixin.get_lookups()

    def test_delist_lookup_with_explicit_name(self):
        """_delist_lookup with explicit lookup_name."""

        class FakeLookup:
            lookup_name = "original_name"

        class MyMixin(RegisterLookupMixin):
            pass

        MyMixin.register_lookup(FakeLookup, lookup_name="custom_name")
        assert "custom_name" in MyMixin.get_lookups()

        MyMixin._delist_lookup(FakeLookup, lookup_name="custom_name")
        MyMixin._clear_cached_lookups()
        assert "custom_name" not in MyMixin.get_lookups()


# ---------------------------------------------------------------------------
# Tests: Node._new_instance
# ---------------------------------------------------------------------------
class TestNodeNewInstance:
    def test_new_instance_creates_node(self):
        """_new_instance creates a Node with given children, connector, negated."""
        node = Node._new_instance(children=[("a", 1)], connector="AND", negated=False)
        assert isinstance(node, Node)
        assert node.children == [("a", 1)]
        assert node.connector == "AND"
        assert node.negated is False

    def test_new_instance_preserves_subclass(self):
        """_new_instance sets __class__ to cls."""
        node = Q._new_instance(children=[("b", 2)], connector="OR", negated=True)
        assert type(node) is Q
        assert node.children == [("b", 2)]
        assert node.negated is True


# ---------------------------------------------------------------------------
# Tests: Node.__contains__
# ---------------------------------------------------------------------------
class TestNodeContains:
    def test_contains_direct_child(self):
        """__contains__ returns True for direct children."""
        child = ("name", "Alice")
        node = Node(children=[child, ("age", 30)])
        assert child in node
        assert ("missing", "value") not in node

    def test_contains_node_child(self):
        """__contains__ works with Node children."""
        child_node = Node(children=[("x", 1)])
        parent = Node(children=[child_node])
        assert child_node in parent


# ---------------------------------------------------------------------------
# Tests: Node.add
# ---------------------------------------------------------------------------
class TestNodeAdd:
    def test_add_duplicate_data_returns_data(self):
        """Adding data already in children returns data without duplicating."""
        child = ("name", "Alice")
        node = Node(children=[child], connector="AND")
        result = node.add(child, "AND")
        assert result == child
        assert len(node.children) == 1

    def test_add_with_squash_false(self):
        """squash=False appends without squashing."""
        node = Node(children=[("a", 1)], connector="AND")
        new_data = ("b", 2)
        result = node.add(new_data, "AND", squash=False)
        assert result == new_data
        assert new_data in node.children
        assert len(node.children) == 2

    def test_add_with_different_connector(self):
        """Different connector restructures the tree."""
        node = Node(children=[("a", 1), ("b", 2)], connector="AND")
        new_data = ("c", 3)
        result = node.add(new_data, "OR")
        assert result == new_data
        assert node.connector == "OR"
        assert len(node.children) == 2
        assert node.children[1] == new_data
        assert isinstance(node.children[0], Node)
        assert node.children[0].connector == "AND"

    def test_add_same_connector_non_squashable_node(self):
        """Same connector but negated node appends as child."""
        node = Node(children=[("a", 1)], connector="AND")
        negated_node = Node(children=[("b", 2)], connector="AND", negated=True)
        result = node.add(negated_node, "AND")
        assert result == negated_node
        assert len(node.children) == 2

    def test_add_same_connector_squashable_node(self):
        """Same connector, non-negated node gets squashed."""
        node = Node(children=[("a", 1), ("b", 2)], connector="AND")
        squashable = Node(children=[("c", 3), ("d", 4)], connector="AND")
        result = node.add(squashable, "AND")
        assert result is node
        assert len(node.children) == 4

    def test_add_single_child_node_squashed(self):
        """Single-child node gets squashed regardless of connector."""
        node = Node(children=[("a", 1)], connector="AND")
        single = Node(children=[("b", 2)], connector="OR")
        result = node.add(single, "AND")
        assert result is node
        assert ("b", 2) in node.children


# ---------------------------------------------------------------------------
# Tests: Node dunder methods
# ---------------------------------------------------------------------------
class TestNodeDunderMethods:
    def test_str_negated(self):
        """__str__ with negated produces NOT format."""
        node = Node(children=[("a", 1)], connector="AND", negated=True)
        assert "NOT" in str(node)

    def test_repr(self):
        """__repr__ includes class name."""
        node = Node(children=[("a", 1)], connector="AND")
        assert "Node" in repr(node)

    def test_deepcopy(self):
        """__deepcopy__ creates a proper copy."""
        original = Node(children=[("a", 1), ("b", 2)], connector="AND")
        copied = copy.deepcopy(original)
        assert copied == original
        assert copied is not original
        assert copied.children is not original.children

    def test_len(self):
        """__len__ returns number of children."""
        node = Node(children=[("a", 1), ("b", 2)])
        assert len(node) == 2

    def test_bool_true(self):
        node = Node(children=[("a", 1)])
        assert bool(node) is True

    def test_bool_false(self):
        node = Node()
        assert bool(node) is False

    def test_eq(self):
        """__eq__ compares class, connector, negated, children."""
        n1 = Node(children=[("a", 1)], connector="AND")
        n2 = Node(children=[("a", 1)], connector="AND")
        assert n1 == n2

    def test_negate(self):
        """negate flips negated."""
        node = Node(children=[("a", 1)])
        assert node.negated is False
        node.negate()
        assert node.negated is True


# ---------------------------------------------------------------------------
# Tests: Q._combine and operators
# ---------------------------------------------------------------------------
class TestQCombine:
    def test_combine_with_non_q_raises_typeerror(self):
        """_combine raises TypeError for non-Q."""
        q = Q(name="Alice")
        with pytest.raises(TypeError):
            q._combine("not a Q", "AND")

    def test_combine_with_empty_other(self):
        """When other is empty, returns deepcopy of self."""
        q = Q(name="Alice")
        empty = Q()
        result = q._combine(empty, "AND")
        assert result == q
        assert result is not q

    def test_combine_with_empty_self(self):
        """When self is empty, returns deepcopy of other."""
        empty = Q()
        q = Q(name="Alice")
        result = empty._combine(q, "AND")
        assert result == q
        assert result is not q

    def test_or_operator(self):
        """__or__ uses OR connector."""
        q1 = Q(name="Alice")
        q2 = Q(age=30)
        result = q1 | q2
        assert result.connector == Q.OR

    def test_and_operator(self):
        """__and__ uses AND connector."""
        q1 = Q(name="Alice")
        q2 = Q(age=30)
        result = q1 & q2
        assert result.connector == Q.AND

    def test_invert(self):
        """__invert__ negates the Q."""
        q = Q(name="Alice")
        result = ~q
        assert result.negated is True
