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
import click


@click.group(invoke_without_command=True)
@click.version_option()
@click.pass_context
def main(ctx):
    """CLI utilities for the Protean"""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
def test():
    # Standard Library Imports
    import sys

    import pytest

    errno = pytest.main(["-vv", "--cache-clear", "--flake8"])

    sys.exit(errno)


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
@click.argument("domain")
@click.argument("domain_file", type=click.Path(exists=True))
@click.option("-b", "--broker", default="default")
def server(domain, domain_file, broker):
    """Run Async Background Server"""
    # FIXME Accept MAX_WORKERS as command-line input as well
    from protean.server import Server

    server = Server(domain=domain, domain_file=domain_file, broker=broker)
    server.run()
