import os
import re
import shutil
import subprocess
from typing import List, Optional

import typer
from copier import run_copy
from rich.console import Console
from typing_extensions import Annotated

import protean

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


def new(
    project_name: Annotated[str, typer.Argument()],
    output_folder: Annotated[
        str, typer.Option("--output-dir", "-o", show_default=False)
    ] = ".",
    data: Annotated[List[str], typer.Option("--data", "-d", show_default=False)] = [],
    pretend: Annotated[Optional[bool], typer.Option("--pretend", "-p")] = False,
    force: Annotated[Optional[bool], typer.Option("--force", "-f")] = False,
    defaults: Annotated[Optional[bool], typer.Option("--defaults")] = False,
    skip_setup: Annotated[Optional[bool], typer.Option("--skip-setup")] = False,
):
    def is_valid_project_name(project_name):
        """
        Validates the project name against criteria that ensure compatibility across
        Mac, Linux, and Windows systems, and also disallows spaces.
        """
        # Define a regex pattern that disallows the specified special characters
        # and spaces. This pattern also disallows leading and trailing spaces.
        forbidden_characters = re.compile(r'[<>:"/\\|?*\s]')

        if forbidden_characters.search(project_name) or not project_name:
            return False

        return True

    def clear_directory_contents(dir_path):
        """
        Removes all contents of a specified directory without deleting the directory itself.

        Parameters:
            dir_path (str): The path to the directory whose contents are to be cleared.
        """
        for item in os.listdir(dir_path):
            item_path = os.path.join(dir_path, item)
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path)  # Remove files and links
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)  # Remove subdirectories and their contents

    if not is_valid_project_name(project_name):
        raise ValueError("Invalid project name")

    # Ensure the output folder exists
    if not os.path.isdir(output_folder):
        raise FileNotFoundError(f'Output folder "{output_folder}" does not exist')

    # The output folder is named after the project, and placed in the target folder
    project_directory = os.path.join(output_folder, project_name)

    # If the project folder already exists, and --force is not set, raise an error
    if os.path.isdir(project_directory) and os.listdir(project_directory):
        if not force:
            raise FileExistsError(
                f'Folder "{project_name}" is not empty. Use --force to overwrite.'
            )
        # Clear the directory contents if --force is set
        clear_directory_contents(project_directory)

    # Convert data tuples to a dictionary, if provided
    data_dict = {}
    for value in data:
        k, v = value.split("=", 1)
        data_dict[k] = v

    # Add the project name to answers
    data_dict["project_name"] = project_name

    # Create project from repo template
    run_copy(
        f"{protean.__path__[0]}/template",
        project_directory or ".",
        data=data_dict,
        unsafe=True,  # Trust our own template implicitly,
        defaults=defaults,
        pretend=pretend,
    )

    # Run post-generation setup unless skipped or in pretend mode
    if not skip_setup and not pretend:
        run_project_setup(project_directory)  # pragma: no cover
