"""Tests for the Options container in utils/container.py."""

import pytest

from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.fields import Identifier
from protean.utils.container import Options


class TestOptionsEdgeCases:
    def test_options_init_with_none(self):
        """Options(None) defaults to empty dict."""
        opts = Options(None)
        assert opts["abstract"] is False

    def test_options_delattr_missing_key(self):
        """__delattr__ for missing key raises AttributeError."""
        opts = Options({})
        with pytest.raises(
            AttributeError, match="'Options' object has no attribute 'nonexistent'"
        ):
            del opts.nonexistent

    def test_options_add(self):
        """__add__ merges two Options."""
        opts1 = Options({"key1": "val1"})
        opts2 = Options({"key2": "val2"})
        merged = opts1 + opts2
        assert merged["key1"] == "val1"
        assert merged["key2"] == "val2"
        assert isinstance(merged, Options)


class TestMutableDefaultOptions:
    def test_mutating_one_class_default_leaves_another_class_unchanged(
        self, test_domain
    ):
        """A list default is copied into each class's ``meta_``, so a change
        made through one class does not show up in another."""

        class Ledger(BaseProjection):
            ledger_id: Identifier(identifier=True)

        class FirstProjector(BaseProjector):
            pass

        class SecondProjector(BaseProjector):
            pass

        test_domain.register(Ledger)
        first = test_domain.register(
            FirstProjector, projector_for=Ledger, stream_categories=["ledger"]
        )
        second = test_domain.register(
            SecondProjector, projector_for=Ledger, stream_categories=["ledger"]
        )

        first.meta_.aggregates.append("x")

        assert second.meta_.aggregates == []
