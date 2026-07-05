"""Regression tests for ``protean.utils.query.Node`` equality."""

from protean.utils.query import Node


def test_node_equals_matching_node():
    assert Node() == Node()


def test_node_equality_with_unrelated_object_is_false():
    """Comparing a Node to a non-Node must return False, not raise.

    Regression: ``Node.__eq__`` cast ``other`` to a Node and accessed
    ``.connector``/``.negated``/``.children``, so comparing to an unrelated
    object raised ``AttributeError`` instead of returning ``NotImplemented``
    (which Python turns into ``False``).
    """
    node = Node()
    assert (node == "not a node") is False
    assert (node == 42) is False
    assert (node == object()) is False
    assert node != "not a node"
