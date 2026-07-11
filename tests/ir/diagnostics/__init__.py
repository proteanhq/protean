"""Tests for `protean check` diagnostics and architecture fitness functions.

One test file per diagnostic / fitness rule. When you add a new rule, create a
new ``test_<rule>.py`` here — do **not** append to an existing file. (This
package was split out of a single 3,800-line module that every rule PR appended
to, which made it a constant merge-conflict hotspot.) Shared domain builders and
helpers live in ``_helpers.py``; broader shared fixtures live in the sibling
``tests/ir/elements.py`` and ``tests/ir/support.py``. ``conftest.py`` applies
``no_test_domain`` to the whole package (these tests build their own domains),
so a new file needs no marker.
"""
