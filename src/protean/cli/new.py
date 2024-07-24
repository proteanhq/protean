import os
import re
import shutil
from typing import List, Optional

import typer
from copier import run_copy
from typing_extensions import Annotated

import protean


def new(
    project_name: Annotated[str, typer.Argument()],
    output_folder: Annotated[
        str, typer.Option("--output-dir", "-o", show_default=False)
    ] = ".",
    data: Annotated[List[str], typer.Option("--data", "-d", show_default=False)] = [],
    pretend: Annotated[Optional[bool], typer.Option("--pretend", "-p")] = False,
    force: Annotated[Optional[bool], typer.Option("--force", "-f")] = False,
    defaults: Annotated[Optional[bool], typer.Option("--defaults")] = False,
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
