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
# Protean
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
    import pytest
    import sys

    errno = pytest.main(["-vv", "--cache-clear", "--flake8"])

    sys.exit(errno)


@main.command()
def new():
    from cookiecutter.main import cookiecutter

    # Create project from the cookiecutter-protean.git repo template
    cookiecutter("gh:proteanhq/cookiecutter-protean")
