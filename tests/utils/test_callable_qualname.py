"""Naming a callable for diagnostics and the IR."""

import functools

from protean.utils import _callable_qualname


def stamp(aggregate):
    pass


class Stamper:
    def __call__(self, aggregate):
        pass

    def method(self, aggregate):
        pass


def test_a_function_is_named_by_module_and_qualname():
    assert _callable_qualname(stamp) == f"{__name__}.stamp"


def test_a_bound_method_is_named_by_its_class_and_name():
    assert _callable_qualname(Stamper().method) == f"{__name__}.Stamper.method"


def test_a_callable_object_is_named_by_its_class():
    assert _callable_qualname(Stamper()) == f"{__name__}.Stamper"


def test_a_partial_is_named_by_the_partial_class():
    assert _callable_qualname(functools.partial(stamp)) == "functools.partial"
