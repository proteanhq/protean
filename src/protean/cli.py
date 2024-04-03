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
import shutil
import subprocess
import sys
import traceback

from enum import Enum
from types import ModuleType
from typing import Optional, Tuple

import typer

from copier import run_copy
from rich import print
from typing_extensions import Annotated

import protean

from protean.exceptions import NoDomainException

# Create the Typer app
#   `no_args_is_help=True` will show the help message when no arguments are passed
app = typer.Typer(no_args_is_help=True)


class Category(str, Enum):
    CORE = "CORE"
    EVENTSTORE = "EVENTSTORE"
    DATABASE = "DATABASE"
    FULL = "FULL"


def find_domain_in_module(module: ModuleType) -> protean.Domain:
    """Given a module instance, find an instance of Protean `Domain` class.

    This method tries to find a protean domain in a given module,
    or raises `NoDomainException` if no domain was detected.

    Process to identify the domain:
    - If `domain` or `subdomain` is present, return that
    - If only one instance of `Domain` is present, return that
    - If multiple instances of `Domain` are present, raise an exception
    - If no instances of `Domain` are present, raise an exception
    """
    from . import Domain

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
    from . import Domain

    # Parse domain_name as a single expression to determine if it's a valid
    # attribute name or function call.
    try:
        expr = ast.parse(domain_name.strip(), mode="eval").body
    except SyntaxError:
        raise NoDomainException(
            {
                "invalid": f"Failed to parse {domain_name!r} as an attribute name or function call."
            }
        )

    if isinstance(expr, ast.Name):
        # Handle attribute name
        name = expr.id
        try:
            domain = getattr(module, name)
        except AttributeError:
            raise NoDomainException(
                {
                    "invalid": f"Failed to find attribute {name!r} in {module.__name__!r}."
                }
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
                        {
                            "invalid": f"{function_name!r} is not callable in {module.__name__!r}."
                        }
                    )
            except AttributeError:
                raise NoDomainException(
                    {
                        "invalid": f"Failed to find function {function_name!r} in {module.__name__!r}."
                    }
                )
        else:
            raise NoDomainException(
                {
                    "invalid": f"Function calls with arguments are not supported: {domain_name!r}."
                }
            )
    else:
        raise NoDomainException(
            {"invalid": f"Failed to parse {domain_name!r} as an attribute name."}
        )

    if not isinstance(domain, Domain):
        raise NoDomainException(
            {
                "invalid": f"A valid Protean domain was not obtained from"
                f" '{module.__name__}:{domain_name}'."
            }
        )

    return domain


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
        return find_domain_in_module(module)
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
        print(f"Loading domain from {domain_import_path}...")
        path, name = (re.split(r":(?![\\/])", domain_import_path, 1) + [None])[:2]
        import_name = prepare_import(path)
        domain = locate_domain(import_name, name)
    else:
        import_name = prepare_import("domain.py")
        domain = locate_domain(import_name, None, raise_if_not_found=False)

    return domain


def version_callback(value: bool):
    if value:
        from protean import __version__

        typer.echo(f"Protean {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool, typer.Option(help="Show version information", callback=version_callback)
    ] = False,
):
    """
    Protean CLI
    """


@app.command()
def test(
    category: Annotated[
        Category, typer.Option("-c", "--category", case_sensitive=False)
    ] = Category.CORE
):
    commands = ["pytest", "--cache-clear", "--ignore=tests/support/"]

    match category.value:
        case "EVENTSTORE":
            # Run tests for EventStore adapters
            # FIXME: Add support for auto-fetching supported event stores
            for store in ["MEMORY", "MESSAGE_DB"]:
                print(f"Running tests for EVENTSTORE: {store}...")
                subprocess.call(commands + ["-m", "eventstore", f"--store={store}"])
        case "DATABASE":
            # Run tests for database adapters
            # FIXME: Add support for auto-fetching supported databases
            for db in ["POSTGRESQL", "SQLITE"]:
                print(f"Running tests for DATABASE: {db}...")
                subprocess.call(commands + ["-m", "database", f"--db={db}"])
        case "FULL":
            # Run full suite of tests with coverage
            # FIXME: Add support for auto-fetching supported adapters
            subprocess.call(
                commands
                + [
                    "--slow",
                    "--sqlite",
                    "--postgresql",
                    "--elasticsearch",
                    "--redis",
                    "--message_db",
                    "--cov=protean",
                    "--cov-config",
                    ".coveragerc",
                    "tests",
                ]
            )

            # Test against each supported database
            for db in ["POSTGRESQL", "SQLITE"]:
                print(f"Running tests for DB: {db}...")

                subprocess.call(commands + ["-m", "database", f"--db={db}"])

            for store in ["MESSAGE_DB"]:
                print(f"Running tests for EVENTSTORE: {store}...")
                subprocess.call(commands + ["-m", "eventstore", f"--store={store}"])
        case _:
            print("Running core tests...")
            subprocess.call(commands)


@app.command()
def new(
    project_name: Annotated[str, typer.Argument()],
    output_folder: Annotated[
        str, typer.Option("--output-dir", "-o", show_default=False)
    ] = ".",
    data: Annotated[
        Tuple[str, str], typer.Option("--data", "-d", show_default=False)
    ] = (None, None),
    pretend: Annotated[Optional[bool], typer.Option("--pretend", "-p")] = False,
    force: Annotated[Optional[bool], typer.Option("--force", "-f")] = False,
):
    def is_valid_project_name(project_name):
        """
        Validates the project name against criteria that ensure compatibility across
        Mac, Linux, and Windows systems, and also disallows spaces.
        """
        # Define a regex pattern that disallows the specified special characters
        # and spaces. This pattern also disallows leading and trailing spaces.
        forbidden_characters = re.compile(r'[<>:"/\\|?*\s]')

        if forbidden_characters.search(project_name) or not project_name:
            return False

        return True

    def clear_directory_contents(dir_path):
        """
        Removes all contents of a specified directory without deleting the directory itself.

        Parameters:
            dir_path (str): The path to the directory whose contents are to be cleared.
        """
        for item in os.listdir(dir_path):
            item_path = os.path.join(dir_path, item)
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path)  # Remove files and links
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)  # Remove subdirectories and their contents

    if not is_valid_project_name(project_name):
        raise ValueError("Invalid project name")

    # Ensure the output folder exists
    if not os.path.isdir(output_folder):
        raise FileNotFoundError(f'Output folder "{output_folder}" does not exist')

    # The output folder is named after the project, and placed in the target folder
    project_directory = os.path.join(output_folder, project_name)

    # If the project folder already exists, and --force is not set, raise an error
    if os.path.isdir(project_directory) and os.listdir(project_directory):
        if not force:
            raise FileExistsError(
                f'Folder "{project_name}" is not empty. Use --force to overwrite.'
            )
        # Clear the directory contents if --force is set
        clear_directory_contents(project_directory)

    # Convert data tuples to a dictionary, if provided
    data = (
        {value[0]: value[1] for value in data} if len(data) != data.count(None) else {}
    )

    # Add the project name to answers
    data["project_name"] = project_name

    # Create project from the cookiecutter-protean.git repo template
    run_copy(
        f"{protean.__path__[0]}/template",
        project_directory or ".",
        data=data,
        unsafe=True,  # Trust our own template implicitly
        defaults=True,  # Use default values for all prompts
        pretend=pretend,
    )


@app.command()
def livereload_docs():
    """Run in shell as `protean livereload-docs`"""
    from livereload import Server, shell

    server = Server()
    server.watch("docs-sphinx/**/*.rst", shell("make html"))
    server.watch("./*.rst", shell("make html"))
    server.serve(root="build/html", debug=True)


@app.command()
def server(
    domain_path: Annotated[str, typer.Argument()] = "",
    test_mode: Annotated[Optional[bool], typer.Option()] = False,
):
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


@app.command()
def generate_docker_compose(
    domain_path: Annotated[str, typer.Argument()] = "",
):
    """Generate a `docker-compose.yml` from Domain config"""
    domain = derive_domain(domain_path)
    domain.init()

    # FIXME Generate docker-compose.yml from domain config
