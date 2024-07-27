import ast
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


def find_domain_by_string(module, domain_name):
    """Check if the given string is a variable name or a function. Call
    a function to get the app instance, or return the variable directly.
    """
    # Parse domain_name as a single expression to determine if it's a valid
    # attribute name or function call.
    try:
        expr = ast.parse(domain_name.strip(), mode="eval").body
    except SyntaxError:
        raise NoDomainException(
            f"Failed to parse {domain_name!r} as an attribute name or function call."
        )

    if isinstance(expr, ast.Name):
        # Handle attribute name
        name = expr.id
        try:
            domain = getattr(module, name)
        except AttributeError:
            raise NoDomainException(
                f"Failed to find attribute {name!r} in {module.__name__!r}."
            )
    elif isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
        # Handle function call, ensuring it's a simple function call without arguments
        function_name = expr.func.id
        if (
            not expr.args
        ):  # Checking for simplicity; no arguments allowed for this example
            try:
                domain_function = getattr(module, function_name)
                if callable(domain_function):
                    domain = domain_function()  # Call the function to get the domain
                else:
                    raise NoDomainException(
                        f"{function_name!r} is not callable in {module.__name__!r}."
                    )
            except AttributeError:
                raise NoDomainException(
                    f"Failed to find function {function_name!r} in {module.__name__!r}."
                )
        else:
            raise NoDomainException(
                f"Function calls with arguments are not supported: {domain_name!r}."
            )
    else:
        raise NoDomainException(
            f"Failed to parse {domain_name!r} as an attribute name."
        )

    if not isinstance(domain, Domain):
        raise NoDomainException(
            f"A valid Protean domain was not obtained from '{module.__name__}:{domain_name}'."
        )

    return domain


def prepare_import(path):
    """Given a filename this will try to calculate the python path, add it
    to the search path and return the actual module name that is expected.
    """
    path = os.path.realpath(path)

    # If the path is ".", look for domain.py or subdomain.py in the current directory
    if path == os.path.realpath("."):
        if os.path.exists(os.path.join(path, "domain.py")):
            path = os.path.join(path, "domain.py")
        elif os.path.exists(os.path.join(path, "subdomain.py")):
            path = os.path.join(path, "subdomain.py")

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


def locate_domain(module_name, domain_name, raise_if_not_found=True):
    __traceback_hide__ = True  # noqa: F841

    try:
        __import__(module_name)
    except ImportError as exc:
        # Reraise the ImportError if it occurred within the imported module.
        # Determine this by checking whether the trace has a depth > 1.
        if sys.exc_info()[2].tb_next:
            raise NoDomainException(
                f"While importing {module_name!r}, an ImportError was"
                f" raised:\n\n{traceback.format_exc()}"
            ) from exc
        elif raise_if_not_found:
            raise NoDomainException(f"Could not import {module_name!r}.") from exc
        else:
            return

    module = sys.modules[module_name]

    if domain_name is None:
        return find_domain_in_module(module)
    else:
        return find_domain_by_string(module, domain_name)


def derive_domain(domain_path: str = None):
    """Derive domain from supplied domain path.

    Domain is derived from sources in this order:
    - Environment variable `PROTEAN_DOMAIN`
    - `domain_path` parameter supplied in console

    Domain path can be:
    - A module in current folder ("hello")
    - A module in a sub folder ("src/hello")
    - A module string ("hello.web")
    - An instance ("hello:app2")
    """
    domain_import_path = os.environ.get("PROTEAN_DOMAIN") or domain_path

    if domain_import_path:
        logger.debug("Deriving domain from %s...", domain_import_path)
        path, name = (re.split(r":(?![\\/])", domain_import_path, 1) + [None])[:2]
        import_name = prepare_import(path)
        domain = locate_domain(import_name, name)
    else:
        import_name = prepare_import("domain.py")
        domain = locate_domain(import_name, None, raise_if_not_found=False)

    return domain
