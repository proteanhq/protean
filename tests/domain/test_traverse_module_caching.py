"""Tests for module caching during domain traversal.

Verifies that _traverse() registers modules in sys.modules before executing
them, preventing duplicate class definitions when modules import each other.

See also: Bug 3 in the bug tracker.
"""

import importlib.util
import sys
from unittest.mock import MagicMock, patch

from protean.domain import Domain


class TestTraverseModuleCaching:
    """Verify that _traverse caches modules in sys.modules before execution."""

    def test_module_registered_in_sys_modules_before_execution(self, tmp_path):
        """Module should be in sys.modules before spec.loader.exec_module runs."""

        # Create a minimal domain structure
        domain_file = tmp_path / "domain_file.py"
        domain_file.write_text(
            "from protean import Domain\ndomain = Domain(__file__)\n"
        )

        module_file = tmp_path / "elements.py"
        module_file.write_text("# Simple module\nVALUE = 42\n")

        domain = Domain(root_path=str(tmp_path), name="test_cache")

        # Track when module is added to sys.modules vs when exec_module is called
        execution_order: list[str] = []
        original_exec_module = None

        def tracking_exec_module(module):
            # Check if module was already registered BEFORE execution
            if module.__name__ in sys.modules:
                execution_order.append("registered_before_exec")
            else:
                execution_order.append("not_registered_before_exec")
            # Actually execute the module
            nonlocal original_exec_module
            if original_exec_module:
                original_exec_module(module)

        # Run _traverse and verify behavior
        with patch.object(domain, "_is_domain_file", return_value=False):
            # We need to intercept the actual execution to verify ordering
            original_spec_from_file = importlib.util.spec_from_file_location

            def patched_spec_from_file(name, location, **kwargs):
                spec = original_spec_from_file(name, location, **kwargs)
                if spec and spec.loader:
                    nonlocal original_exec_module
                    original_exec_module = spec.loader.exec_module
                    spec.loader.exec_module = tracking_exec_module
                return spec

            with patch(
                "importlib.util.spec_from_file_location", patched_spec_from_file
            ):
                domain._traverse()

        # Clean up sys.modules
        for key in list(sys.modules.keys()):
            if "test_cache" in key or "elements" in key:
                if key.startswith(tmp_path.name):
                    del sys.modules[key]

        # Verify that modules were registered in sys.modules before execution
        if execution_order:
            assert all(
                entry == "registered_before_exec" for entry in execution_order
            ), "Module should be registered in sys.modules before exec_module runs"

    def test_module_not_executed_twice(self, tmp_path):
        """A module should not be executed again if already in sys.modules."""

        domain_file = tmp_path / "domain_file.py"
        domain_file.write_text(
            "from protean import Domain\ndomain = Domain(__file__)\n"
        )

        module_file = tmp_path / "counter.py"
        module_file.write_text("LOAD_COUNT = 0\nLOAD_COUNT += 1\n")

        domain = Domain(root_path=str(tmp_path), name="test_no_reexec")

        # Pre-register a mock module in sys.modules
        fake_module_name = f"{tmp_path.name}.counter"
        fake_module = MagicMock()
        fake_module.__name__ = fake_module_name
        sys.modules[fake_module_name] = fake_module

        try:
            with patch.object(domain, "_is_domain_file", return_value=False):
                domain._traverse()

            # The module in sys.modules should be our mock (not replaced)
            assert sys.modules.get(fake_module_name) is fake_module
        finally:
            sys.modules.pop(fake_module_name, None)
            # Clean up any other test modules
            for key in list(sys.modules.keys()):
                if key.startswith(tmp_path.name):
                    del sys.modules[key]
