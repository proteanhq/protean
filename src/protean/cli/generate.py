import logging
import os
from jinja2 import Environment, FileSystemLoader
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
        output_file = os.path.join(os.getcwd(), 'docker-compose.yml')
        if os.path.exists(output_file):
            typer.secho("❌ docker-compose.yml already exists. Aborting.", fg="red")
            raise typer.Exit(code=1)

        # Extract services from domain config
        cfg = domain_instance.config
        services_cfg = getattr(cfg, 'docker', {}).get('services', {})
        services = []
        for name, svc in services_cfg.items():
            services.append({
                'name': name,
                'image': svc.get('image'),
                'ports': svc.get('ports', []),
                'environment': svc.get('environment', {}),
            })

        # Fallback: if no services defined, infer a SQLite service entry
        if not services:
            for provider in getattr(domain_instance, 'providers', {}).values():
                engine = getattr(provider, '_engine', None)
                if engine and engine.url.drivername == 'sqlite':
                    services.append({
                        'name': 'sqlite',
                        'image': 'sqlite',
                        'ports': [],
                        'environment': {},
                    })
                    break

        # Load and render Jinja2 template
        template_dir = os.path.join(os.path.dirname(__file__), 'templates')
        env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template('docker-compose.yml.j2')
        rendered = template.render(services=services)

        # Write rendered output to file
        with open(output_file, 'w') as f:
            f.write(rendered)

        typer.secho(f'✅ docker-compose.yml generated at {output_file}', fg='green')
