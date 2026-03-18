"""Tests for protean.ir module-level utilities."""

import pytest


class TestIRModuleGetattr:
    """Verify deferred import of IRBuilder via __getattr__."""

    def test_import_irbuilder(self):
        from protean.ir import IRBuilder

        assert IRBuilder is not None
        assert IRBuilder.__name__ == "IRBuilder"

    def test_import_diff_ir(self):
        from protean.ir import diff_ir

        assert diff_ir is not None
        assert callable(diff_ir)

    def test_import_classify_changes(self):
        from protean.ir import classify_changes

        assert classify_changes is not None
        assert callable(classify_changes)

    def test_import_compatibility_change(self):
        from protean.ir import CompatibilityChange

        assert CompatibilityChange is not None
        change = CompatibilityChange(
            severity="safe",
            element_fqn="app.Order",
            change_type="element_added",
            message="AGGREGATE 'app.Order' was added",
        )
        assert change.severity == "safe"

    def test_import_compatibility_report(self):
        from protean.ir import CompatibilityReport

        assert CompatibilityReport is not None
        report = CompatibilityReport()
        assert report.is_breaking is False

    def test_load_schema_returns_dict(self):
        from protean.ir import load_schema

        schema = load_schema()
        assert isinstance(schema, dict)
        assert "$schema" in schema or "type" in schema or "properties" in schema

    def test_unknown_attribute_raises(self):
        import protean.ir

        with pytest.raises(AttributeError, match="has no attribute"):
            protean.ir.__getattr__("NoSuchThing")

    def test_import_staleness_result(self):
        from protean.ir import StalenessResult

        assert StalenessResult is not None
        assert StalenessResult.__name__ == "StalenessResult"

    def test_import_staleness_status(self):
        from protean.ir import StalenessStatus

        assert StalenessStatus is not None
        assert StalenessStatus.FRESH.value == "fresh"

    def test_import_check_staleness(self):
        from protean.ir import check_staleness

        assert check_staleness is not None
        assert callable(check_staleness)
