"""Tests for the reusable deprecation machinery in ``protean._deprecation``.

Covers the warning-class hierarchy, the ``warn_deprecated`` helper, the
``@deprecated`` decorator, and the fail-loud behaviour on an unknown removal
version. See #999.
"""

import pathlib
import warnings

import pytest

import protean
from protean._deprecation import (
    ProteanDeprecationWarning,
    RemovedInProtean10Warning,
    RemovedInProtean017Warning,
    RemovedInProtean018Warning,
    deprecated,
    warn_deprecated,
)


class TestMechanismIsTheSingleDeprecationSource:
    """Regression guard for #999's core promise: no deprecation may be
    hand-rolled with a bare ``DeprecationWarning`` and bypass the mechanism.

    A suite-wide ``filterwarnings = error::DeprecationWarning`` flip is not
    viable (a stdlib ``re.split`` positional-``maxsplit`` DeprecationWarning
    already surfaces from ``utils/domain_discovery.py``), so this scans the
    source instead: ``DeprecationWarning`` must appear only in the mechanism.
    """

    def test_deprecation_warning_referenced_only_in_the_mechanism(self):
        root = pathlib.Path(protean.__file__).parent
        offenders = sorted(
            str(py.relative_to(root))
            for py in root.rglob("*.py")
            if py.name != "_deprecation.py"
            and "template" not in py.parts
            and "DeprecationWarning" in py.read_text(encoding="utf-8")
        )
        assert offenders == [], (
            "Hand-rolled DeprecationWarning found; route it through "
            "protean._deprecation (warn_deprecated / @deprecated) instead: "
            f"{offenders}"
        )


class TestWarningHierarchy:
    """Per-version classes are ``DeprecationWarning`` subclasses so the stdlib
    default filters and ``-W`` filtering both work."""

    @pytest.mark.parametrize(
        "cls",
        [
            RemovedInProtean017Warning,
            RemovedInProtean018Warning,
            RemovedInProtean10Warning,
        ],
    )
    def test_subclasses_the_protean_base_and_deprecation_warning(self, cls):
        assert issubclass(cls, ProteanDeprecationWarning)
        assert issubclass(cls, DeprecationWarning)

    def test_base_is_a_deprecation_warning(self):
        assert issubclass(ProteanDeprecationWarning, DeprecationWarning)


class TestWarnDeprecated:
    @pytest.mark.parametrize(
        "removal, expected_cls",
        [
            ("0.17.0", RemovedInProtean017Warning),
            ("0.18.0", RemovedInProtean018Warning),
            ("1.0.0", RemovedInProtean10Warning),
        ],
    )
    def test_removal_version_selects_the_matching_class(self, removal, expected_cls):
        with pytest.warns(expected_cls) as record:
            warn_deprecated("thing", removal=removal)
        assert len(record) == 1
        assert f"Will be removed in v{removal}." in str(record[0].message)

    def test_message_includes_subject_and_alternative(self):
        with pytest.warns(RemovedInProtean017Warning) as record:
            warn_deprecated(
                "--debug",
                removal="0.17.0",
                alternative="Use --log-level DEBUG instead.",
            )
        message = str(record[0].message)
        assert message == (
            "--debug is deprecated. Use --log-level DEBUG instead. "
            "Will be removed in v0.17.0."
        )

    def test_message_omits_alternative_clause_when_not_given(self):
        with pytest.warns(RemovedInProtean017Warning) as record:
            warn_deprecated("--debug", removal="0.17.0")
        assert str(record[0].message) == (
            "--debug is deprecated. Will be removed in v0.17.0."
        )

    def test_stacklevel_attributes_warning_to_the_caller(self):
        """With ``stacklevel=1`` the warning points at the direct caller — this
        test's own frame — not at ``warn_deprecated`` internals."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warn_deprecated("thing", removal="0.17.0", stacklevel=1)
        assert len(caught) == 1
        assert caught[0].filename == __file__

    @pytest.mark.parametrize("removal", ["0.19.0", "0.17", "1.0", "garbage"])
    def test_unknown_removal_version_falls_back_to_base_without_raising(self, removal):
        """Emitting must never crash the live deprecated path: an unregistered
        version degrades to the base class instead of raising."""
        with pytest.warns(ProteanDeprecationWarning) as record:
            warn_deprecated("thing", removal=removal)
        # Exactly the base class, not a per-version subclass.
        assert record[0].category is ProteanDeprecationWarning
        assert f"Will be removed in v{removal}." in str(record[0].message)


class TestDeprecatedDecorator:
    def test_call_emits_the_warning(self):
        @deprecated(removal="0.18.0", alternative="Use the new thing instead.")
        def old_helper():
            return "value"

        with pytest.warns(RemovedInProtean018Warning) as record:
            result = old_helper()

        assert result == "value"
        assert str(record[0].message) == (
            "old_helper() is deprecated. Use the new thing instead. "
            "Will be removed in v0.18.0."
        )

    def test_arguments_are_forwarded_unchanged(self):
        @deprecated(removal="0.18.0")
        def add(a, b, *, c=0):
            return a + b + c

        with pytest.warns(RemovedInProtean018Warning):
            assert add(1, 2, c=3) == 6

    def test_warning_is_attributed_to_the_call_site_not_internals(self):
        """The decorator uses the default ``stacklevel`` — the warning must
        point at the user's call site, not into ``_deprecation.py``'s wrapper.
        A wrong ``+1`` offset would attribute it to the module internals."""

        @deprecated(removal="0.17.0")
        def old_helper():
            return None

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            old_helper()

        assert len(caught) == 1
        assert caught[0].filename == __file__

    def test_functools_wraps_preserves_identity(self):
        @deprecated(removal="0.18.0")
        def documented():
            """Original docstring."""

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "Original docstring."
        assert hasattr(documented, "__wrapped__")

    def test_decoration_does_not_warn_until_called(self):
        """Negative path: decorating is silent — the warning fires only on call."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", ProteanDeprecationWarning)

            @deprecated(removal="0.18.0")
            def never_called():  # pragma: no cover - body intentionally unused
                return None

            # Reaching here means decoration emitted no ProteanDeprecationWarning.
            assert never_called.__name__ == "never_called"

    def test_unknown_removal_version_fails_at_decoration_time(self):
        """Unlike the inline helper, the decorator can validate eagerly — an
        unknown version fails at import, before any user code runs."""
        with pytest.raises(ValueError, match="No Protean deprecation warning class"):

            @deprecated(removal="9.9.9")
            def _f():  # pragma: no cover - never defined; decoration raises
                return None

    def test_decoration_error_lists_the_known_versions(self):
        with pytest.raises(ValueError) as exc:

            @deprecated(removal="9.9.9")
            def _f():  # pragma: no cover - never defined; decoration raises
                return None

        for known in ("0.17.0", "0.18.0", "1.0.0"):
            assert known in str(exc.value)
