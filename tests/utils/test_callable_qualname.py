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


def test_a_partial_is_named_after_the_function_it_wraps():
    assert _callable_qualname(functools.partial(stamp)) == (
        f"functools.partial({__name__}.stamp)"
    )


stamp_lambda = lambda aggregate: None


def test_a_lambda_is_named_by_its_module():
    assert _callable_qualname(stamp_lambda) == f"{__name__}.<lambda>"


def test_a_function_without_a_module_falls_back_to_its_type_module():
    def nameless(aggregate):
        pass

    nameless.__module__ = None
    assert _callable_qualname(nameless).startswith("builtins.")
