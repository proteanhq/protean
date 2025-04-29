import logging

import yaml
import os

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
        config = domain_instance.config

        services = {}

        # Add PostgreSQL if specified
        if config.get("databases", {}).get("default", {}).get("provider") == "postgresql":
            services["postgres"] = {
                "image": "postgres:13",
                "ports": ["5432:5432"]
            }

        # Add Redis if specified
        if config.get("caches", {}).get("default", {}).get("provider") == "redis":
            services["redis"] = {
                "image": "redis:latest",
                "ports": ["6379:6379"]
            }

        # Add the main app container
        services["app"] = {
            "build": ".",
            "ports": ["5000:5000"],
            "depends_on": list(services.keys())[:-1]  # depends on everything else
        }

        compose = {
            "version": "3",
            "services": services
        }

        # Prevent overwriting existing file
        if os.path.exists("docker-compose.yml"):
            typer.echo("docker-compose.yml already exists. Aborting.")
            raise typer.Exit()

        with open("docker-compose.yml", "w") as f:
            yaml.dump(compose, f, default_flow_style=False)

        typer.echo("docker-compose.yml generated successfully.")
