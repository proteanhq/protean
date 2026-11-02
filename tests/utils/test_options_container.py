"""Tests for the Options container in utils/container.py."""

import pytest

from protean.utils.container import Options, OptionsMixin


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
    def test_mutating_one_class_default_leaves_another_class_unchanged(self):
        """A list or dict default is copied into each class's ``meta_``, so
        a change made through one class does not show up in another."""

        class Root(OptionsMixin):
            _default_options = [("tags", []), ("cfg", {})]

        class First(Root):
            meta_ = Options()

        class Second(Root):
            meta_ = Options()

        First.meta_.tags.append("x")
        First.meta_.cfg["k"] = "v"

        assert Second.meta_.tags == []
        assert Second.meta_.cfg == {}
