import logging
import os
import pkgutil
import sys

logger = logging.getLogger("protean.application")


def get_env():
    """Get the environment the app is running in, indicated by the
    :envvar:`PROTEAN_ENV` environment variable. The default is
    ``'production'``.
    """
    return os.environ.get("PROTEAN_ENV") or "production"


def get_debug_flag():
    """Get whether debug mode should be enabled for the app, indicated
    by the :envvar:`PROTEAN_DEBUG` environment variable. The default is
    ``True`` if :func:`.get_env` returns ``'development'``, or ``False``
    otherwise.
    """
    val = os.environ.get("PROTEAN_DEBUG")

    if not val:
        return get_env() == "development"

    return val.lower() not in ("0", "false", "no")


def get_root_path(import_name):
    """Returns the path to a package or cwd if that cannot be found.  This
    returns the path of a package or the folder that contains a module.

    Not to be confused with the package path returned by :func:`find_package`.
    """
    # Module already imported and has a file attribute.  Use that first.
    mod = sys.modules.get(import_name)
    if mod is not None and hasattr(mod, "__file__"):
        return os.path.dirname(os.path.abspath(mod.__file__))

    # Next attempt: check the loader.
    loader = pkgutil.get_loader(import_name)

    # Loader does not exist or we're referring to an unloaded main module
    # or a main module without path (interactive sessions), go with the
    # current working directory.
    if loader is None or import_name == "__main__":
        return os.getcwd()

    # For .egg, zipimporter does not have get_filename until Python 2.7.
    # Some other loaders might exhibit the same behavior.
    if hasattr(loader, "get_filename"):
        filepath = loader.get_filename(import_name)
    else:
        # Fall back to imports.
        __import__(import_name)
        mod = sys.modules[import_name]
        filepath = getattr(mod, "__file__", None)

        # If we don't have a filepath it might be because we are a
        # namespace package.  In this case we pick the root path from the
        # first module that is contained in our package.
        if filepath is None:
            raise RuntimeError(
                "No root path can be found for the provided "
                'module "%s".  This can happen because the '
                "module came from an import hook that does "
                "not provide file name information or because "
                "it's a namespace package.  In this case "
                "the root path needs to be explicitly "
                "provided." % import_name,
            )

    # filepath is import_name.py for a module, or __init__.py for a package.
    return os.path.dirname(os.path.abspath(filepath))


class _PackageBoundObject(object):
    #: The name of the package or module that this app belongs to. Do not
    #: change this once it is set by the constructor.
    import_name = None

    #: Absolute path to the package on the filesystem. Used to look up
    #: resources contained in the package.
    root_path = None

    def __init__(self, import_name, template_folder=None, root_path=None):
        self.import_name = import_name

        if root_path is None:
            root_path = get_root_path(self.import_name)

        self.root_path = root_path
