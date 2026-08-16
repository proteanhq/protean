import inspect
import pickle

import pytest

from protean.exceptions import (
    ConfigurationError,
    DatabaseError,
    IncorrectUsageError,
    ObjectNotFoundError,
    ProteanException,
    ProteanExceptionWithMessage,
    ValidationError,
)
from protean.ir.diagnostics import DiagnosticCode, resolve


def test_pickling_of_exceptions():
    exc = ObjectNotFoundError("foo")

    pickled_exc = pickle.dumps(exc)
    unpickled_exc = pickle.loads(pickled_exc)

    assert exc.args[0] == unpickled_exc.args[0]


class TestCodedException:
    """A raise site may attach a DiagnosticCode; the exception then carries the
    code, its location, and the registry rationale/fix."""

    def test_no_code_leaves_the_diagnostic_attributes_none(self):
        # Every existing raise passes no code, so nothing changes for it.
        exc = ConfigurationError("plain")
        assert exc.code is None
        assert exc.location is None
        assert exc.rationale is None
        assert exc.fix is None

    def test_code_and_location_are_carried(self):
        exc = IncorrectUsageError(
            "boom",
            code=DiagnosticCode.USAGE_NOT_A_PROJECTION,
            location="Domain.view_for",
        )
        assert exc.code == "USAGE_NOT_A_PROJECTION"
        assert exc.location == "Domain.view_for"

    def test_code_is_stored_as_a_plain_string(self):
        exc = IncorrectUsageError("boom", code=DiagnosticCode.USAGE_NOT_A_PROJECTION)
        assert type(exc.code) is str

    def test_rationale_and_fix_resolve_from_the_registry(self):
        code = DiagnosticCode.USAGE_NOT_A_PROJECTION
        meta = resolve(code)
        exc = IncorrectUsageError("boom", code=code)
        assert exc.rationale == meta.rationale
        assert exc.fix == meta.fix

    def test_code_and_location_survive_a_pickle_round_trip(self):
        exc = IncorrectUsageError(
            "boom",
            code=DiagnosticCode.USAGE_ELEMENT_NOT_REGISTERED,
            location="Domain.repository_for",
        )
        restored = pickle.loads(pickle.dumps(exc))

        assert restored.args[0] == "boom"
        assert restored.code == "USAGE_ELEMENT_NOT_REGISTERED"
        assert restored.location == "Domain.repository_for"
        # rationale/fix recompute from the code, so they survive too.
        assert restored.fix == resolve(DiagnosticCode.USAGE_ELEMENT_NOT_REGISTERED).fix

    def test_code_survives_pickling_on_with_message_exceptions(self):
        exc = ValidationError(
            {"field": ["bad"]},
            code=DiagnosticCode.CONFIG_ELEMENT_NOT_REGISTERED,
            location="Domain._get_element_by_name",
        )
        restored = pickle.loads(pickle.dumps(exc))

        # The concrete subclass survives, so `except ValidationError` past the
        # broker still catches it.
        assert type(restored) is ValidationError
        assert restored.messages == {"field": ["bad"]}
        assert restored.code == "CONFIG_ELEMENT_NOT_REGISTERED"
        assert restored.location == "Domain._get_element_by_name"
        # rationale/fix still resolve after the round-trip.
        assert restored.fix == resolve(DiagnosticCode.CONFIG_ELEMENT_NOT_REGISTERED).fix

    def test_an_unknown_code_reads_as_none_rather_than_raising(self):
        # A code renamed or removed since the exception was pickled still
        # deserializes and keeps its `code` string; only rationale/fix read None.
        exc = ConfigurationError("boom")
        exc.code = "A_CODE_THIS_VERSION_DOES_NOT_KNOW"

        assert exc.rationale is None
        assert exc.fix is None
        assert exc.code == "A_CODE_THIS_VERSION_DOES_NOT_KNOW"

    def test_reduce_does_not_serialize_unpicklable_subclass_state(self):
        # DatabaseError.original_exception is often a live driver error that does
        # not pickle. The old whole-__dict__ state broke pickling here; carrying
        # only the diagnostic attributes keeps it working, code intact.
        class Unpicklable:
            def __reduce__(self):
                raise TypeError("cannot pickle a live driver error")

        exc = DatabaseError(
            "db down",
            original_exception=Unpicklable(),  # type: ignore[arg-type]
            code=DiagnosticCode.CONFIG_EVENT_STORE_NOT_INITIALIZED,
            location="Domain._require_event_store",
        )
        restored = pickle.loads(pickle.dumps(exc))

        assert restored.args[0] == "db down"
        assert restored.code == "CONFIG_EVENT_STORE_NOT_INITIALIZED"
        assert restored.location == "Domain._require_event_store"
        # The unpicklable payload is dropped, as it was before codes existed.
        assert restored.original_exception is None

    def test_extra_info_is_not_carried_across_pickle(self):
        # extra_info was dropped on unpickle before codes existed; keep it that
        # way, so an unpicklable extra_info can never break serialization.
        exc = IncorrectUsageError(
            "boom",
            extra_info={"anything": "here"},
            code=DiagnosticCode.USAGE_NOT_A_PROJECTION,
        )
        restored = pickle.loads(pickle.dumps(exc))

        assert restored.extra_info is None
        assert restored.code == "USAGE_NOT_A_PROJECTION"


class TestMultipleCodes:
    """A single raise may carry several codes (invariants failing together);
    ``codes`` holds them all, and ``code`` names the single one or ``None``."""

    def test_codes_default_empty_and_code_none(self):
        exc = ConfigurationError("plain")
        assert exc.codes == []
        assert exc.code is None

    def test_a_single_code_populates_both_code_and_codes(self):
        exc = ValidationError({"f": ["bad"]}, code=DiagnosticCode.INVARIANT_POST_FAILED)
        assert exc.code == "INVARIANT_POST_FAILED"
        assert exc.codes == ["INVARIANT_POST_FAILED"]

    def test_several_codes_leave_code_none_and_fill_codes(self):
        exc = ValidationError(
            {"f": ["bad"]},
            codes=[
                DiagnosticCode.INVARIANT_POST_FAILED,
                DiagnosticCode.INVARIANT_PRE_FAILED,
            ],
        )
        assert exc.code is None
        assert exc.codes == ["INVARIANT_POST_FAILED", "INVARIANT_PRE_FAILED"]

    def test_codes_are_stored_as_plain_strings(self):
        # Both a DiagnosticCode member and a bare string normalize to str.
        exc = ValidationError(
            {"f": ["bad"]},
            codes=[DiagnosticCode.INVARIANT_POST_FAILED, "APP_SPECIFIC_CODE"],
        )
        assert exc.codes == ["INVARIANT_POST_FAILED", "APP_SPECIFIC_CODE"]
        assert all(type(c) is str for c in exc.codes)

    def test_codes_survive_a_pickle_round_trip(self):
        exc = ValidationError(
            {"f": ["bad"]},
            codes=[DiagnosticCode.INVARIANT_POST_FAILED, "APP_SPECIFIC_CODE"],
            location="Order",
        )
        restored = pickle.loads(pickle.dumps(exc))

        assert type(restored) is ValidationError
        assert restored.codes == ["INVARIANT_POST_FAILED", "APP_SPECIFIC_CODE"]
        assert restored.code is None
        assert restored.location == "Order"

    def test_a_scalar_string_code_is_carried(self):
        # ``code`` widened to accept a plain string, not only a DiagnosticCode.
        exc = ValidationError({"f": ["bad"]}, code="APP_CODE")
        assert exc.code == "APP_CODE"
        assert exc.codes == ["APP_CODE"]

    def test_a_repeated_code_dedupes_so_code_stays_set(self):
        # Dedup lives in the constructor, so one distinct code keeps ``code`` set.
        exc = ValidationError({"f": ["bad"]}, codes=["A_CODE", "A_CODE"])
        assert exc.codes == ["A_CODE"]
        assert exc.code == "A_CODE"

    def test_a_bare_string_passed_as_codes_is_one_code_not_split(self):
        # ``str`` is itself a Sequence[str]; a lone string must not split into
        # per-character codes.
        exc = ValidationError({"f": ["bad"]}, codes="APP_CODE")
        assert exc.codes == ["APP_CODE"]
        assert exc.code == "APP_CODE"

    def test_codes_wins_when_both_code_and_codes_are_given(self):
        exc = ValidationError({"f": ["bad"]}, code="SCALAR", codes=["A", "B"])
        assert exc.codes == ["A", "B"]
        assert exc.code is None


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
