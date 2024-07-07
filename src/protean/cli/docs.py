import subprocess

import typer

app = typer.Typer(no_args_is_help=True)


"""
If we want to create a CLI app with one single command but
still want it to be a command/subcommand, we need to add a callback (see below).

This can be removed when we have more than one command/subcommand.

https://typer.tiangolo.com/tutorial/commands/one-or-multiple/#one-command-and-one-callback
"""


@app.callback()
def callback():
    pass


@app.command()
def preview():
    """Run a live preview server"""
    try:
        subprocess.call(["mkdocs", "serve", "--dev-addr=0.0.0.0:8000"])
    except KeyboardInterrupt:
        pass
