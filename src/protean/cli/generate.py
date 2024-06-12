import logging

import typer
from typing_extensions import Annotated

from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain

logger = logging.getLogger(__name__)

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
def docker_compose(
    domain: Annotated[str, typer.Option()] = ".",
):
    """Generate a `docker-compose.yml` from Domain config"""
    try:
        domain_instance = derive_domain(domain)
    except NoDomainException as exc:
        logger.error(f"Error loading Protean domain: {exc.messages}")
        raise typer.Abort()

    print(f"Generating docker-compose.yml for domain at {domain}")

    with domain_instance.domain_context():
        domain_instance.init()

        # FIXME Generate docker-compose.yml from domain config
