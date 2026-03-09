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

    def test_unknown_attribute_raises(self):
        import protean.ir

        with pytest.raises(AttributeError, match="has no attribute"):
            protean.ir.__getattr__("NoSuchThing")
