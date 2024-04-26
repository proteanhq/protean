"""Run an interactive Python shell in the context of a given
    Protean domain.  The domain will populate the default
    namespace of this shell according to its configuration.

    This is useful for executing small snippets of code
    without having to manually configure the application.

    FIXME: Populate context in a decorator like Flask does:
        https://github.com/pallets/flask/blob/b90a4f1f4a370e92054b9cc9db0efcb864f87ebe/src/flask/cli.py#L368
        https://github.com/pallets/flask/blob/b90a4f1f4a370e92054b9cc9db0efcb864f87ebe/src/flask/cli.py#L984
    """

import sys
import typing

import typer

from IPython.terminal.embed import InteractiveShellEmbed
from typing_extensions import Annotated

from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain


def shell(domain: Annotated[str, typer.Option()] = "."):
    domain_instance = derive_domain(domain)
    if not domain_instance:
        raise NoDomainException(
            "Could not locate a Protean domain. You should provide a domain in"
            '"PROTEAN_DOMAIN" environment variable or pass a domain file in options'
        )

    with domain_instance.domain_context():
        domain_instance.init()

        ctx: dict[str, typing.Any] = {}
        ctx.update(domain_instance.make_shell_context())

        banner = (
            f"Python {sys.version} on {sys.platform}\n"
            f"    location: {sys.executable}\n"
            f"Domain: {domain_instance.name}\n"
        )
        ipshell = InteractiveShellEmbed(banner1=banner, user_ns=ctx)

        ipshell()
