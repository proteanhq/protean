""" Module defines utilities for importing modules and packages """

import importlib.util

from importlib import import_module


def perform_import(val):
    """
    If the given setting is a string import notation,
    then perform the necessary import or imports.
    """
    if val is not None:
        if isinstance(val, str):
            return import_from_string(val)
        elif isinstance(val, (list, tuple)):
            return [import_from_string(item) for item in val]

    return val


def import_from_string(val, package=None):
    """
    Attempt to import a class from a string representation.
    """
    try:
        module_path, class_name = val.rsplit(".", 1)
        module = import_module(module_path, package=package)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        msg = f"Could not import {val}. {e.__class__.__name__}: {e}"
        raise ImportError(msg)


def import_from_full_path(domain, path):
    spec = importlib.util.spec_from_file_location(domain, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    return getattr(mod, domain)
