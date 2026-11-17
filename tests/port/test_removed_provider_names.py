"""The provider names of the database port are gone, with no aliases."""

import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "protean.port.provider",
        "protean.adapters.repository",
        "protean.adapters.repository.memory",
    ],
)
def test_old_module_paths_do_not_import(module):
    with pytest.raises(ImportError):
        importlib.import_module(module)


@pytest.mark.parametrize("name", ["Database", "Cache"])
def test_removed_enums_do_not_import(name):
    with pytest.raises(ImportError):
        exec(f"from protean.utils import {name}", {})
