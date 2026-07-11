"""Support fixtures for IR builder tests that require real importable modules.

Some diagnostics (e.g. INFRA_IMPORT_IN_DOMAIN) resolve an element's ``module``
to a source file with ``importlib.util.find_spec`` and AST-parse it. Elements
defined inline inside a test function share the test module's source, so a
dedicated importable module is needed to exercise those on-paths faithfully.
"""
