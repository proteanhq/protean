"""
Module that contains the command line app.

Why does this file exist, and why not put this in __main__?

  You might be tempted to import things from __main__ later, but that will cause
  problems: the code will get executed twice:

  - When you run `python -mprotean` python will execute
    ``__main__.py`` as a script. That means there won't be any
    ``protean.__main__`` in ``sys.modules``.
  - When you import __main__ it will get executed again (as a module) because
    there's no ``protean.__main__`` in ``sys.modules``.

  Also see (1) from http://click.pocoo.org/5/setuptools/#setuptools-integration
"""
import ast
import os
import re
import sys
import traceback

import click


class NoDomainException(click.UsageError):
    """Raised if a domain cannot be found or loaded."""


@click.group(invoke_without_command=True)
@click.version_option()
@click.pass_context
def main(ctx):
    """CLI utilities for Protean"""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def find_best_domain(module):
    """Given a module instance this tries to find the best possible
    application in the module or raises an exception.
    """
    from . import Domain

    # Search for the most common names first.
    for attr_name in ("domain", "subdomain"):
        domain = getattr(module, attr_name, None)

        if isinstance(domain, Domain):
            return domain

    # Otherwise find the only object that is a Flask instance.
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
    from . import Domain

    # Parse domain_name as a single expression to determine if it's a valid
    # attribute name or function call.
    try:
        expr = ast.parse(domain_name.strip(), mode="eval").body
    except SyntaxError:
        raise NoDomainException(
            f"Failed to parse {domain_name!r} as an attribute name or function call."
        )

    if isinstance(expr, ast.Name):
        name = expr.id
    else:
        raise NoDomainException(
            f"Failed to parse {domain_name!r} as an attribute name."
        )

    try:
        domain = getattr(module, name)
    except AttributeError:
        raise NoDomainException(
            f"Failed to find attribute {name!r} in {module.__name__!r}."
        )

    if isinstance(domain, Domain):
        return domain

    raise NoDomainException(
        "A valid Protean domain was not obtained from"
        f" '{module.__name__}:{domain_name}'."
    )


def prepare_import(path):
    """Given a filename this will try to calculate the python path, add it
    to the search path and return the actual module name that is expected.
    """
    path = os.path.realpath(path)

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
    except ImportError:
        # Reraise the ImportError if it occurred within the imported module.
        # Determine this by checking whether the trace has a depth > 1.
        if sys.exc_info()[2].tb_next:
            raise NoDomainException(
                f"While importing {module_name!r}, an ImportError was"
                f" raised:\n\n{traceback.format_exc()}"
            )
        elif raise_if_not_found:
            raise NoDomainException(f"Could not import {module_name!r}.")
        else:
            return

    module = sys.modules[module_name]

    if domain_name is None:
        return find_best_domain(module)
    else:
        return find_domain_by_string(module, domain_name)


def derive_domain(domain_path):
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
        click.secho(f"Loading domain from {domain_import_path}...")
        path, name = (re.split(r":(?![\\/])", domain_import_path, 1) + [None])[:2]
        import_name = prepare_import(path)
        domain = locate_domain(import_name, name)
    else:
        import_name = prepare_import("domain.py")
        domain = locate_domain(import_name, None, raise_if_not_found=False)

    return domain


@main.command()
@click.option("-c", "--category")
def test(category):
    import subprocess

    if category:
        if category == "EVENTSTORE":
            for store in ["MEMORY", "MESSAGE_DB"]:
                print(f"Running tests for EVENTSTORE: {store}...")
                subprocess.call(["pytest", "-m", "eventstore", f"--store={store}"])
    else:
        # Run full suite
        subprocess.call(
            [
                "pytest",
                "--cache-clear",
                "--slow",
                "--sqlite",
                "--postgresql",
                "--elasticsearch",
                "--redis",
                "--message_db",
                "tests",
            ]
        )

        # Test against each supported database
        for db in ["POSTGRESQL", "ELASTICSEARCH", "SQLITE"]:
            print(f"Running tests for DB: {db}...")

            subprocess.call(
                ["pytest", f"--db={db}", "tests/adapters/repository/test_generic.py"]
            )

        for store in ["MEMORY", "MESSAGE_DB"]:
            print(f"Running tests for EVENTSTORE: {store}...")
            subprocess.call(["pytest", "-m", "eventstore", f"--store={store}"])


@main.command()
def new():
    from cookiecutter.main import cookiecutter

    # Create project from the cookiecutter-protean.git repo template
    cookiecutter("gh:proteanhq/cookiecutter-protean")


@main.command()
def livereload_docs():
    """Run in shell as `protean livereload-docs`"""
    from livereload import Server, shell

    server = Server()
    server.watch("docs/**/*.rst", shell("make html"))
    server.watch("./*.rst", shell("make html"))
    server.serve(root="build/html", debug=True)


@main.command()
@click.option("-d", "--domain-path")
@click.option("-t", "--test-mode", is_flag=True)
def server(domain_path, test_mode):
    """Run Async Background Server"""
    # FIXME Accept MAX_WORKERS as command-line input as well
    from protean.server import Engine

    domain = derive_domain(domain_path)
    if not domain:
        raise NoDomainException(
            "Could not locate a Protean domain. You should provide a domain in"
            '"PROTEAN_DOMAIN" environment variable or pass a domain file in options '
            'and a "domain.py" module was not found in the current directory.'
        )

    engine = Engine(domain, test_mode=test_mode)
    engine.run()
