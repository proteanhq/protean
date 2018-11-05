""" Module defines utilities for importing modules and packages """

from importlib import import_module


def perform_import(val):
    """
    If the given setting is a string import notation,
    then perform the necessary import or imports.
    """
    if val is None:
        return None
    elif isinstance(val, str):
        return import_from_string(val)
    elif isinstance(val, (list, tuple)):
        return [import_from_string(item) for item in val]
    return val


def import_from_string(val):
    """
    Attempt to import a class from a string representation.
    """
    try:
        module_path, class_name = val.rsplit('.', 1)
        module = import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        msg = f"Could not import {val}. {e.__class__.__name__}: {e}"
        raise ImportError(msg)
