"""Prevent pytest from collecting mypy fixture files.

These .py files are inputs for mypy (invoked via the mypy API in
test_mypy_plugin.py). They contain reveal_type() calls that do not
exist at runtime and will fail at import time.
"""

collect_ignore_glob = ["*.py"]
