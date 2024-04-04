import typer

from typing_extensions import Annotated

from protean.utils.domain import derive_domain

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback():
    """
    If we want to create a CLI app with one single command but
    still want it to be a command/subcommand, we need to add a callback.

    This can be removed when we have more than one command/subcommand.

    https://typer.tiangolo.com/tutorial/commands/one-or-multiple/#one-command-and-one-callback
    """


@app.command()
def docker_compose(
    domain_path: Annotated[str, typer.Argument()],
):
    """Generate a `docker-compose.yml` from Domain config"""
    print(f"Generating docker-compose.yml for domain at {domain_path}")
    domain = derive_domain(domain_path)

    with domain.domain_context():
        domain.init()

        # FIXME Generate docker-compose.yml from domain config
