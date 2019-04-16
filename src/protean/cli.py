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
import platform

from . import __version__


def get_version():
    message = (
        'Python %(python)s\n'
        'Protean %(protean)s'
    )
    click.echo(message % {
        'python': platform.python_version(),
        'protean': __version__
    })


@click.group(invoke_without_command=True)
@click.option('-v', '--version', is_flag=True)
@click.pass_context
def main(ctx, version):
    """CLI utilities for the Protean"""
    if version:
        get_version()

    if not version and ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
def test():
    import pytest
    import sys

    errno = pytest.main(['-v', '--flake8'])

    sys.exit(errno)
