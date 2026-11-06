import ast
import glob
import logging
import os
import re
import sys
import traceback
from types import ModuleType

from protean import Domain
from protean.exceptions import NoDomainException

logger = logging.getLogger(__name__)


def find_domain_in_module(module: ModuleType) -> Domain:
    """Given a module instance, find an instance of Protean `Domain` class.

    This method tries to find a protean domain in a given module,
    or raises `NoDomainException` if no domain was detected.

    Process to identify the domain:
    - If `domain` or `subdomain` is present, return that
    - If only one instance of `Domain` is present, return that
    - If multiple instances of `Domain` are present, raise an exception
    - If no instances of `Domain` are present, raise an exception
    """
    # Search for the most common names first.
    for attr_name in ("domain", "subdomain"):
        domain = getattr(module, attr_name, None)

        if isinstance(domain, Domain):
            return domain

    # Otherwise find the only object that is a Domain instance.
    matches = [v for v in module.__dict__.values() if isinstance(v, Domain)]

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        raise NoDomainException(
            "Detected multiple Protean domains in module"
            f" {module.__name__!r}. Use 'PROTEAN_DOMAIN={module.__name__}:name'"
            f" to specify the correct one."
        )

    raise NoDomainException(
        "Failed to find Protean domain in module"
        f" {module.__name__!r}. Use 'PROTEAN_DOMAIN={module.__name__}:name'"
        " to specify one."
    )


def _domain_from_attribute(module: ModuleType, name: str) -> object:
    """Return the attribute *name* of *module*."""
    try:
        return getattr(module, name)
    except AttributeError as e:
        raise NoDomainException(
            f"Failed to find attribute {name!r} in {module.__name__!r}."
        ) from e


def _domain_from_call(
    module: ModuleType, function_name: str, args: list[ast.expr], domain_name: str
) -> object:
    """Call the function *function_name* of *module* and return its result.

    Raises ``NoDomainException`` if the call passes *args*, since only a
    call without arguments is supported.
    """
    if args:
        raise NoDomainException(
            f"Function calls with arguments are not supported: {domain_name!r}."
        )
    try:
        domain_function = getattr(module, function_name)
        if callable(domain_function):
            return domain_function()  # Call the function to get the domain
        raise NoDomainException(
            f"{function_name!r} is not callable in {module.__name__!r}."
        )
    except AttributeError as e:
        raise NoDomainException(
            f"Failed to find function {function_name!r} in {module.__name__!r}."
        ) from e


def find_domain_by_string(module: ModuleType, domain_name: str) -> Domain:
    """Check if the given string is a variable name or a function. Call
    a function to get the app instance, or return the variable directly.
    """
    # Parse domain_name as a single expression to determine if it's a valid
    # attribute name or function call.
    try:
        expr = ast.parse(domain_name.strip(), mode="eval").body
    except SyntaxError as e:
        raise NoDomainException(
            f"Failed to parse {domain_name!r} as an attribute name or function call."
        ) from e

    if isinstance(expr, ast.Name):
        domain = _domain_from_attribute(module, expr.id)
    elif isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
        domain = _domain_from_call(module, expr.func.id, expr.args, domain_name)
    else:
        raise NoDomainException(
            f"Failed to parse {domain_name!r} as an attribute name."
        )

    if not isinstance(domain, Domain):
        raise NoDomainException(
            f"A valid Protean domain was not obtained from '{module.__name__}:{domain_name}'."
        )

    return domain


_DOMAIN_FILENAMES = ("domain.py", "subdomain.py")


def _find_src_domain_file(directory: str) -> str | None:
    """Return the one `src/*/domain.py` or `src/*/subdomain.py` under *directory*.

    `domain.py` files are searched first; `subdomain.py` files only when
    there is no `domain.py`. Returns None when nothing matches. Raises
    `NoDomainException` listing every match when more than one file of the
    same name matches.
    """
    for filename in _DOMAIN_FILENAMES:
        matches = sorted(
            glob.glob(os.path.join(glob.escape(directory), "src", "*", filename))
        )
        if len(matches) == 1:
            return matches[0]
        if matches:
            listed = ", ".join(os.path.relpath(match, directory) for match in matches)
            raise NoDomainException(
                f"Found more than one domain under 'src': {listed}."
                " Pass --domain to choose one."
            )
    return None


def _find_domain_file(directory: str) -> str | None:
    """Return the domain file for *directory*: `domain.py` or `subdomain.py`
    in *directory* itself, else the one found under `src/`, else None."""
    for filename in _DOMAIN_FILENAMES:
        candidate = os.path.join(directory, filename)
        if os.path.exists(candidate):
            return candidate
    return _find_src_domain_file(directory)


def prepare_import(path: str) -> str:
    """Given a filename this will try to calculate the python path, add it
    to the search path and return the actual module name that is expected.

    A path that resolves to the current directory is replaced by its domain
    file: `domain.py` or `subdomain.py` in the directory, else the single
    `src/*/domain.py` or `src/*/subdomain.py`. Raises `NoDomainException`
    when more than one file matches under `src/`.
    """
    path = os.path.realpath(path)

    if path == os.path.realpath("."):
        path = _find_domain_file(path) or path

    filename, ext = os.path.splitext(path)
    if ext == ".py":
        path = filename

    if os.path.basename(path) == "__init__":
        path = os.path.dirname(path)

    module_name = []

    # move up until outside package structure (no __init__.py)
    while True:
        path, name = os.path.split(path)
        module_name.append(name)

        if not os.path.exists(os.path.join(path, "__init__.py")):
            break

    if sys.path[0] != path:
        sys.path.insert(0, path)

    return ".".join(module_name[::-1])


def locate_domain(
    module_name: str, domain_name: str | None, raise_if_not_found: bool = True
) -> Domain | None:
    __traceback_hide__ = True  # noqa: F841

    try:
        __import__(module_name)
    except ImportError as exc:
        # Reraise the ImportError if it occurred within the imported module.
        # Determine this by checking whether the trace has a depth > 1.
        tb = sys.exc_info()[2]
        if tb is not None and tb.tb_next:
            raise NoDomainException(
                f"While importing {module_name!r}, an ImportError was"
                f" raised:\n\n{traceback.format_exc()}"
            ) from exc
        elif raise_if_not_found:
            raise NoDomainException(f"Could not import {module_name!r}.") from exc
        else:
            return None

    module = sys.modules[module_name]

    if domain_name is None:
        return find_domain_in_module(module)
    else:
        return find_domain_by_string(module, domain_name)


def derive_domain(domain_path: str | None = None) -> Domain | None:
    """Derive domain from supplied domain path.

    Domain is derived from sources in this order:
    - Environment variable `PROTEAN_DOMAIN`
    - `domain_path` parameter supplied in console

    Domain path can be:
    - A module in current folder ("hello")
    - A module in a sub folder ("src/hello")
    - A module string ("hello.web")
    - An instance ("hello:app2")

    With no path, and with the path ".", the domain is looked up in this
    order: `domain.py` or `subdomain.py` in the current folder, then
    `src/*/domain.py`, then `src/*/subdomain.py`. More than one match under
    `src/` raises `NoDomainException`. With no path and no match, returns
    None.
    """
    domain_import_path = os.environ.get("PROTEAN_DOMAIN") or domain_path

    if domain_import_path:
        logger.debug("Deriving domain from %s...", domain_import_path)
        parts = re.split(r":(?![\\/])", domain_import_path, maxsplit=1)
        path = parts[0]
        name = parts[1] if len(parts) > 1 else None
        import_name = prepare_import(path)
        domain = locate_domain(import_name, name)
    else:
        domain = _derive_default_domain()

    return domain


def _derive_default_domain() -> Domain | None:
    """Load the domain for the current folder when no path is given.

    Returns None when the folder has no `domain` or `subdomain` module and
    nothing matches under `src/`.
    """
    # A `domain` or `subdomain` package in the current folder keeps loading
    # the way it did before the file and `src/` lookup existed.
    has_local_package = os.path.isdir("domain") or os.path.isdir("subdomain")
    domain_file = None if has_local_package else _find_domain_file(".")
    if domain_file is not None:
        return locate_domain(prepare_import(domain_file), None)

    import_name = prepare_import("domain.py")
    return locate_domain(import_name, None, raise_if_not_found=False)
