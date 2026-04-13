"""Run an interactive Python shell in the context of a given
Protean domain.  The domain will populate the default
namespace of this shell according to its configuration.

This is useful for executing small snippets of code
without having to manually configure the application.

"""

import sys
import typing

import typer
from IPython.terminal.embed import InteractiveShellEmbed
from typing_extensions import Annotated

from protean.cli._helpers import handle_cli_exceptions
from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

logger = get_logger(__name__)


@handle_cli_exceptions("shell")
def shell(
    domain: Annotated[str, typer.Option()] = ".",
    traverse: Annotated[bool, typer.Option()] = False,
):
    try:
        domain_instance = derive_domain(domain)
    except NoDomainException as exc:
        logger.error(f"Error loading Protean domain: {exc.args[0]}")
        raise typer.Abort()

    if domain_instance is None:
        logger.error("Could not derive a Protean domain")
        raise typer.Abort()

    if traverse:
        print("Traversing directory to load all modules...")
    domain_instance.init(traverse=traverse)

    with domain_instance.domain_context():
        ctx: dict[str, typing.Any] = {}
        ctx.update(domain_instance.make_shell_context())

        banner = (
            f"Python {sys.version} on {sys.platform}\n"
            f"    location: {sys.executable}\n"
            f"Domain: {domain_instance.name}\n"
        )
        ipshell = InteractiveShellEmbed(banner1=banner, user_ns=ctx)

        ipshell()
