import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from protean.cli._helpers import CTX_LOG_CONFIGURED, abort_for_missing_dependency
from protean.scaffold.create_project import create_project

console = Console()


def run_project_setup(project_directory: str) -> None:  # pragma: no cover
    """Run post-generation setup for the new project.

    This method handles:
    - Installing dependencies with uv
    - Initializing git repository
    - Installing pre-commit hooks
    - Setting activation script permissions
    - Displaying quick start instructions

    Args:
        project_directory: Path to the newly created project directory
    """
    console.print("\n🚀 Setting up your Protean project...", style="bold green")

    # Change to project directory for setup commands
    original_dir = os.getcwd()
    os.chdir(project_directory)

    try:
        # Find uv executable
        uv_path = shutil.which("uv")
        if not uv_path:
            console.print(
                "  uv not found. Install it from https://docs.astral.sh/uv/",
                style="yellow",
            )
            return

        # Install project dependencies with uv (creates .venv automatically)
        console.print("📚 Installing dependencies with uv...", style="cyan")
        subprocess.run(
            [uv_path, "sync", "--all-extras", "--all-groups"],
            check=True,
        )

        # Initialize git repository first (required for pre-commit)
        console.print("📝 Initializing Git repository...", style="cyan")
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "add", "."], check=True, capture_output=True)

        # Install pre-commit hooks if pre-commit is available
        console.print("🔧 Installing pre-commit hooks...", style="cyan")
        pre_commit_path = (
            os.path.join(".venv", "bin", "pre-commit")
            if os.name != "nt"
            else os.path.join(".venv", "Scripts", "pre-commit")
        )
        if os.path.exists(pre_commit_path):
            # Run pre-commit install with the venv environment
            subprocess.run([pre_commit_path, "install"], check=True)
        else:
            console.print(
                "  Pre-commit not found, skipping hook installation", style="yellow"
            )

        console.print("\n✅ Project setup complete!", style="bold green")

        # Generate activation command based on shell and OS
        shell = os.environ.get("SHELL", "").lower()
        if os.name == "nt":  # Windows
            activate_cmd = ".venv\\Scripts\\activate"
        elif "fish" in shell:
            activate_cmd = "source .venv/bin/activate.fish"
        elif "csh" in shell or "tcsh" in shell:
            activate_cmd = "source .venv/bin/activate.csh"
        else:  # Default to bash/zsh
            activate_cmd = "source .venv/bin/activate"

        console.print("\nTo start working on your project:", style="yellow")
        console.print(f"  cd {project_directory}", style="bold")
        console.print(f"  {activate_cmd}", style="bold")
        console.print("\nThen you can start developing with:", style="yellow")
        console.print("  protean shell", style="bold")
        console.print("  protean test", style="bold")

        # The activation scripts are created by the template in scripts/ folder
        # Make sure they have the right permissions
        # Since we're already in the project directory, use relative paths
        activate_sh = "scripts/activate.sh"
        activate_bat = "scripts/activate.bat"
        activate_fish = "scripts/activate.fish"

        if os.path.exists(activate_sh):
            os.chmod(activate_sh, 0o755)
        if os.path.exists(activate_fish):
            os.chmod(activate_fish, 0o755)

        # Detect user's shell
        shell = os.environ.get("SHELL", "")

        # Show quick start based on OS and shell
        console.print("\n💡 Quick Start:", style="cyan bold")
        if os.name == "nt" and os.path.exists(activate_bat):
            console.print(f"  {activate_bat}", style="bold green")
        elif "fish" in shell and os.path.exists(activate_fish):
            console.print(f"  source {activate_fish}", style="bold green")
        elif os.path.exists(activate_sh):
            console.print(f"  source {activate_sh}", style="bold green")

        console.print("\nThis will:", style="yellow")
        console.print("  • Change to your project directory", style="white")
        console.print("  • Deactivate any current virtual environment", style="white")
        console.print("  • Activate your project's virtual environment", style="white")

    except subprocess.CalledProcessError as e:
        console.print(f"\n⚠️  Setup encountered an error: {e}", style="bold red")
        console.print("You can complete the setup manually.", style="yellow")
    finally:
        # Return to original directory for now
        # (can't change parent shell's directory from subprocess)
        os.chdir(original_dir)


def _run_from_model(
    project_name: str,
    output_folder: str,
    model_file: str,
    force: bool,
    log_already_configured: bool = False,
) -> int:
    """Build a project from a text event model and verify it, return the exit code.

    Runs the pipeline in this order: parse the model, create the project (with the
    example slice off), promote the parsed model to a slice, apply it, then run
    ``verify`` in-process and report the verdict. Parse comes first so an invalid
    model aborts before any directory is created. This composes the callable cores
    only. It does not run ``uv sync``, git init, or pre-commit.

    Returns the code the ``new`` command should exit with:

    - ``2`` for a bad model file (unreadable, non-UTF-8, or rejected by the
      grammar) or a create-time usage error (bad name, missing ``-o`` folder, a
      non-empty target without ``--force``). Nothing is written in these cases,
      so no directory is left behind.
    - ``1`` when the model parses but the slice cannot be generated or applied,
      or when the project package has the same name as a module already imported
      here, so verifying it in this process would read the wrong code. The
      project directory was already created, so it is left in place and the
      message says so.
    - the verify core's mapped code (0 on pass, otherwise its failure code).

    The create-time ``ImportError`` path (the ``[scaffold]`` extra is missing)
    does not return: ``abort_for_missing_dependency`` raises ``typer.Exit``.
    """
    # Local imports keep ``protean --help`` from pulling the parser, the slice
    # generator, and the IR stack in on every CLI start (the same reason
    # ``verify`` and ``check`` import their heavy machinery lazily).
    from protean.cli.result import route_logs_to_stderr  # noqa: PLC0415
    from protean.cli.verify import (  # noqa: PLC0415
        _render_check_detail,
        _render_pytest_tail,
        run_verify,
    )
    from protean.scaffold.add_plan import (  # noqa: PLC0415
        AddPlanError,
        _resolve_project,
    )
    from protean.scaffold.apply import ApplyError, apply_plan  # noqa: PLC0415
    from protean.scaffold.model_parser import (  # noqa: PLC0415
        ModelParseError,
        parse_model,
    )
    from protean.scaffold.slice_generator import (  # noqa: PLC0415
        SliceFragment,
        SliceGeneratorError,
        generate_slice_plan,
    )

    # 1. Read and parse the model before anything is written, so a missing or
    #    unreadable file or a model the grammar rejects aborts here, so no
    #    directory is left behind. A non-UTF-8 file raises ``UnicodeDecodeError``,
    #    which is a ``ValueError`` (not an ``OSError``), so catch it too.
    try:
        model_text = Path(model_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        typer.echo(f"Error: could not read model file {model_file!r}: {exc}")
        return 2
    try:
        fragment_mapping = parse_model(model_text)
    except ModelParseError as exc:
        # ``ModelParseError`` stringifies as "line N: <message>", so this carries
        # the line number the violation is reported at.
        typer.echo(f"Error: {exc}")
        return 2

    # 2. Create the project with the example slice off, so the generated slice's
    #    paths are clear, so ``apply_plan`` (create-only) does not hit a target
    #    that already exists. ``create_project`` validates the name, the output
    #    folder, and the target up front and raises before writing anything, so a
    #    caught failure here leaves no directory behind.
    try:
        create_project(
            project_name,
            output_folder,
            {"include_example": "false"},
            force=force,
            defaults=True,
        )
    except ImportError as exc:
        abort_for_missing_dependency("scaffold", "'protean new --from-model'", exc)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        typer.echo(f"Error: {exc}")
        return 2

    project_directory = os.path.join(output_folder, project_name)

    # 3-6. Promote the parsed model to a slice and write it into the new project.
    #    The parser is looser than the generator (it does not cross-check a
    #    command's or event's fields against the aggregate), so a model that
    #    parses can still be rejected here. The plan does not add rollback, so
    #    surface a one-line error and say the directory was left in place, rather
    #    than crashing with a traceback.
    try:
        fragment = SliceFragment.from_mapping(fragment_mapping)
        package, domain_var = _resolve_project(project_directory)
        plan = generate_slice_plan(fragment, package, domain_var)
        apply_plan(project_directory, plan)
    except (SliceGeneratorError, AddPlanError, ApplyError) as exc:
        typer.echo(f"Error: could not build the slice from the model: {exc}")
        typer.echo(f"The project directory {project_directory!r} was left in place.")
        return 1

    # 7. Verify the new project in-process and report the verdict. ``run_verify``
    #    imports the generated package by its dotted name, so a package that has
    #    the same name as a module this process already imported (a project named
    #    ``protean``, ``json``, ``typer``) resolves to the cached module instead
    #    of the new code, and the verdict would describe that module rather than
    #    the project just built. Say so instead of reporting a wrong verdict. A
    #    fresh process does not help for a name the CLI itself imports, so the
    #    way out is a different project name.
    if package in sys.modules:
        typer.echo(
            f"Error: the project package {package!r} has the same name as a module "
            "Protean has already imported, so the new project cannot be verified "
            "in place. Use a different project name."
        )
        typer.echo(f"The project directory {project_directory!r} was left in place.")
        return 1

    # ``run_verify`` returns the result instead of exiting, so map its code to
    # this command's exit. Route logs to stderr first: ``run_verify`` imports the
    # generated domain, whose import-time logs would otherwise land on stdout.
    # Skip that when the CLI's --log-config/--log-level/--log-format callback
    # already configured logging, so that configuration is not discarded.
    route_logs_to_stderr(log_already_configured=log_already_configured)
    domain_path = os.path.join(project_directory, "src", package, "domain.py")
    # ``derive_domain`` gives ``PROTEAN_DOMAIN`` precedence over the path it is
    # handed, so a value left in the environment would have verify initialize an
    # unrelated domain and report a verdict about the wrong project. Drop it for
    # the call (the tests stage inherits this environment, so the project's own
    # pytest run is covered too) and put it back afterwards.
    previous_protean_domain = os.environ.pop("PROTEAN_DOMAIN", None)
    try:
        result = run_verify(f"{domain_path}:{domain_var}", project_directory)
    finally:
        if previous_protean_domain is not None:
            os.environ["PROTEAN_DOMAIN"] = previous_protean_domain

    verdict = "PASS" if result.exit_code == 0 else "FAIL"
    console.print(f"\n  Protean verify: [bold]{verdict}[/bold]")
    # A usage or init failure carries its reason on ``error_line`` and leaves the
    # stage detail below empty, so print it first — otherwise a failed build
    # reports only "FAIL" and "init fail".
    if result.error_line:
        console.print(f"    [red]{escape(result.error_line)}[/red]")
    for stage, info in result.stages.items():
        console.print(f"    {stage:<7} {info['status']}")
    # On a failure, print the check diagnostics and the pytest tail, the same
    # detail ``protean verify`` shows, so the user can act on the failure instead
    # of seeing only "FAIL".
    if result.exit_code != 0:
        _render_check_detail(result.stages.get("check", {}))
        if result.stages.get("tests", {}).get("status") == "fail":
            _render_pytest_tail(result.tests_output)
    return result.exit_code


def new(
    ctx: typer.Context,
    project_name: Annotated[str, typer.Argument()],
    output_folder: Annotated[
        str, typer.Option("--output-dir", "-o", show_default=False)
    ] = ".",
    data: Annotated[
        list[str] | None, typer.Option("--data", "-d", show_default=False)
    ] = None,
    pretend: Annotated[bool, typer.Option("--pretend", "-p")] = False,
    force: Annotated[bool, typer.Option("--force", "-f")] = False,
    defaults: Annotated[bool, typer.Option("--defaults")] = False,
    skip_setup: Annotated[bool, typer.Option("--skip-setup")] = False,
    from_model: Annotated[
        str | None,
        typer.Option(
            "--from-model",
            show_default=False,
            help="Build the project from a text event-model file and verify it",
        ),
    ] = None,
) -> None:
    # ``--from-model`` is its own pipeline (parse, create, generate, apply,
    # verify). It composes the callable cores and skips post-generation setup, so
    # it does not use the flags below (``--data``, ``--pretend``, ``--skip-setup``).
    # It does honour ``--force``, threading it into ``create_project`` so an
    # existing target can be overwritten the same way a plain ``new`` does.
    if from_model is not None:
        # Thread the CLI callback's "logging is already configured" flag through,
        # so ``--log-config``/``--log-level``/``--log-format`` survive the
        # stderr-routing call this path makes before it imports the new domain.
        parent_obj = ctx.obj or {}
        raise typer.Exit(
            code=_run_from_model(
                project_name,
                output_folder,
                from_model,
                force,
                log_already_configured=bool(parent_obj.get(CTX_LOG_CONFIGURED)),
            )
        )

    if data is None:
        data = []

    # Parse the CLI's ``-d key=value`` strings into the plain dict the core
    # takes. The core injects ``project_name`` itself.
    data_dict = {}
    for value in data:
        k, v = value.split("=", 1)
        data_dict[k] = v

    # The core owns the file-producing work (name validation, target resolution,
    # --force clear, copier render, manifest, AGENTS.md) and imports copier as
    # its first statement. Translate an absent [scaffold] extra into an install
    # hint here; the core raises before it clears any directory, so a lean
    # install never wipes an existing target.
    try:
        planned = create_project(
            project_name,
            output_folder,
            data_dict,
            dry_run=pretend,
            force=force,
            defaults=defaults,
        )
    except ImportError as exc:
        abort_for_missing_dependency("scaffold", "'protean new'", exc)

    # Under --pretend nothing was written; echo the files that would be created
    # so the user still sees the plan.
    if pretend:
        for path in planned:
            typer.echo(path)
        return

    # Run post-generation setup unless skipped.
    project_directory = os.path.join(output_folder, project_name)
    if not skip_setup:
        run_project_setup(project_directory)  # pragma: no cover
