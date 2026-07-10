import inspect
import pickle

import pytest

from protean.exceptions import (
    ObjectNotFoundError,
    ProteanException,
    ProteanExceptionWithMessage,
)


def test_pickling_of_exceptions():
    exc = ObjectNotFoundError("foo")

    pickled_exc = pickle.dumps(exc)
    unpickled_exc = pickle.loads(pickled_exc)

    assert exc.args[0] == unpickled_exc.args[0]


class TestProteanException:
    @pytest.fixture
    def exception_instance(self):
        return ProteanException("An error occurred")

    def test_exception_initialization(self, exception_instance):
        assert exception_instance.args[0] == "An error occurred"
        assert exception_instance.extra_info is None

    def test_exception_with_extra_info(self):
        exception_instance = ProteanException(
            "An error occurred", extra_info="Extra info"
        )
        assert exception_instance.extra_info == "Extra info"

    def test_exception_no_args(self):
        exception_instance = ProteanException()
        assert exception_instance.args == ()

    def test_exception_multiple_args(self):
        exception_instance = ProteanException(
            "Error 1", "Error 2", extra_info="Extra info"
        )
        assert exception_instance.args == ("Error 1", "Error 2")
        assert exception_instance.extra_info == "Extra info"


class TestProteanExceptionWithMessage:
    def test_exception_initialization(self):
        messages = {"error": "An error occurred"}
        exception_instance = ProteanExceptionWithMessage(messages)

        assert exception_instance.messages == {"error": "An error occurred"}
        assert exception_instance.traceback is None

    def test_exception_str(self):
        messages = {"error": "An error occurred"}
        exception_instance = ProteanExceptionWithMessage(messages)

        assert str(exception_instance) == "{'error': 'An error occurred'}"

    def test_exception_str_with_string_messages(self):
        # Non-dict ``messages`` (a bare string) exercise the
        # ``return f"{self.messages}"`` branch of ``__str__``.
        exception_instance = ProteanExceptionWithMessage("some error")

        assert str(exception_instance) == "some error"

    def test_exception_str_with_list_messages(self):
        # Non-dict ``messages`` (a list) also flow through the
        # ``return f"{self.messages}"`` branch of ``__str__``.
        exception_instance = ProteanExceptionWithMessage(["a", "b"])

        assert str(exception_instance) == "['a', 'b']"

    def test_exception_reduce(self):
        messages = {"error": "An error occurred"}
        exception_instance = ProteanExceptionWithMessage(messages)

        reduced = exception_instance.__reduce__()
        assert reduced[0] is ProteanExceptionWithMessage
        assert reduced[1] == ({"error": "An error occurred"},)

    def test_exception_with_traceback(self):
        messages = {"error": "An error occurred"}
        traceback = "Traceback info"
        exception_instance = ProteanExceptionWithMessage(messages, traceback=traceback)

        assert exception_instance.traceback == traceback

    def test_exception_with_additional_kwargs(self):
        messages = {"error": "An error occurred"}
        extra_info = "Extra info"
        exception_instance = ProteanExceptionWithMessage(
            messages, extra_info=extra_info
        )

        assert exception_instance.messages == messages
        assert exception_instance.traceback is None
        assert exception_instance.extra_info == extra_info


class TestPublicSurface:
    """`protean.exceptions.__all__` freezes the module's star-export."""

    def _star_import(self):
        namespace: dict[str, object] = {}
        exec("from protean.exceptions import *", namespace)
        return {name for name in namespace if not name.startswith("__")}

    def _defined_exception_classes(self):
        # Exception classes *defined in this module* (not imported into it).
        from protean import exceptions

        return {
            name
            for name, obj in inspect.getmembers(exceptions, inspect.isclass)
            if issubclass(obj, exceptions.ProteanException)
            and obj.__module__ == exceptions.__name__
        }

    def test_all_reconciles_with_defined_exceptions(self):
        # The guard that actually catches drift: `__all__` must be exactly the
        # exception classes defined here plus the re-exported deprecation
        # category. Adding a `class FooError(ProteanException)` without listing
        # it, or dropping a public exception from `__all__`, fails here.
        from protean import exceptions

        assert set(exceptions.__all__) == self._defined_exception_classes() | {
            "ProteanDeprecationWarning"
        }

    def test_star_import_binds_exactly_the_public_surface(self):
        # Not `set(__all__)` on the RHS — that would be tautological. Pin to the
        # independently-derived surface so a name silently dropped from `__all__`
        # (and thus from `import *`) is caught here too.
        assert self._star_import() == self._defined_exception_classes() | {
            "ProteanDeprecationWarning"
        }

    def test_every_exported_name_is_a_deprecation_category_or_exception(self):
        from protean import exceptions
        from protean._deprecation import ProteanDeprecationWarning

        for name in exceptions.__all__:
            obj = getattr(exceptions, name)
            assert isinstance(obj, type)
            if name == "ProteanDeprecationWarning":
                assert issubclass(obj, ProteanDeprecationWarning)
            else:
                assert issubclass(obj, exceptions.ProteanException)

    def test_incidental_imports_are_not_exported(self):
        # `logging`, `datetime`, and `Any` are non-underscore module-level
        # imports that `import *` would drag in without an explicit `__all__`;
        # their absence proves the guard actually filters.
        exported = self._star_import()
        assert "logging" not in exported
        assert "datetime" not in exported
        assert "Any" not in exported
