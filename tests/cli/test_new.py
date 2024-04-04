import os

from pathlib import Path

import pytest

from typer.testing import CliRunner

from protean.cli import app

runner = CliRunner()

PROJECT_NAME = "foobar"


@pytest.mark.slow
class TestGenerator:
    def test_successful_project_generation(self):
        with runner.isolated_filesystem() as current_dir:
            with runner.isolated_filesystem() as project_dir:
                args = ["new", PROJECT_NAME, "-o", project_dir]

                # Switch to the target directory
                os.chdir(current_dir)

                result = runner.invoke(app, args)

                assert result.exit_code == 0

                # Output folder should be the specified target directory
                assert len(os.listdir(project_dir)) > 0
                assert os.path.isfile(f"{project_dir}/{PROJECT_NAME}/README.rst")
                with open(f"{project_dir}/{PROJECT_NAME}/README.rst") as f:
                    assert f.readline() == "========\n"

    def test_output_directory_is_current_directory_if_not_specified(self):
        # Create a temporary directory
        with runner.isolated_filesystem() as current_dir:
            with runner.isolated_filesystem():
                args = ["new", "foobar"]

                # Switch to the target directory
                os.chdir(current_dir)

                result = runner.invoke(app, args)

                assert result.exit_code == 0

                # Output folder should be the current working directory
                assert len(os.listdir(current_dir)) > 0
                assert os.path.isfile(f"{current_dir}/{PROJECT_NAME}/README.rst")

    def test_pretend_project_generation(self):
        # Create a temporary directory
        with runner.isolated_filesystem() as project_dir:
            args = ["new", "foobar", "--pretend"]
            result = runner.invoke(app, args)

            assert result.exit_code == 0

            # Output folder should not exist
            assert len(os.listdir(project_dir)) == 0

    def test_invalid_output_folder_throws_error(self):
        args = ["new", PROJECT_NAME, "-o", "baz"]
        result = runner.invoke(app, args)

        assert result.exit_code == 1
        assert isinstance(result.exception, FileNotFoundError)
        assert result.exception.args[0] == 'Output folder "baz" does not exist'

    def test_nonempty_output_folder_throws_error(self):
        # Create a temporary directory
        with runner.isolated_filesystem() as project_dir:
            # Create a non-empty directory
            os.makedirs(f"{project_dir}/{PROJECT_NAME}")
            Path(f"{project_dir}/{PROJECT_NAME}/file.txt").touch()

            # Specify the non-empty directory as the output folder
            args = ["new", PROJECT_NAME, "-o", project_dir]
            result = runner.invoke(app, args)

            assert result.exit_code == 1
            assert isinstance(result.exception, FileExistsError)
            assert result.exception.args[0] == (
                f'Folder "{PROJECT_NAME}" is not empty. Use --force to overwrite.'
            )

    def test_nonempty_output_folder_can_be_overwritten_explicitly(self):
        # Create a temporary directory
        with runner.isolated_filesystem() as project_dir:
            # Create a non-empty directory
            os.makedirs(f"{project_dir}/{PROJECT_NAME}")

            temp_file = f"{project_dir}/{PROJECT_NAME}/file.txt"
            Path(temp_file).touch()

            # Pass --force to generate output into the non-empty directory
            args = ["new", "foobar", "-o", project_dir, "--force"]
            result = runner.invoke(app, args)

            assert result.exit_code == 0
            assert result.exception is None
            assert os.path.isfile(f"{project_dir}/{PROJECT_NAME}/README.rst")
            assert not os.path.exists(temp_file), "File should not exist"

    def test_project_generation_in_unwritable_directory(self):
        # Create a temporary directory
        with runner.isolated_filesystem() as project_dir:
            # Make the directory unwritable
            os.chmod(project_dir, 0o400)

            args = ["new", "unwritable_project", "-o", project_dir]
            result = runner.invoke(app, args)

            # Restore the permissions for cleanup
            os.chmod(project_dir, 0o700)

            assert result.exit_code != 0
            assert result.exception.args[1] == "Permission denied"

    @pytest.mark.parametrize(
        "invalid_project_name",
        [
            "project<name",
            "project>name",
            "project:name",
            'project"name',
            "project/name",
            "project\\name",
            "project|name",
            "project?name",
            "project*name",
            "project name",  # Including spaces as per requirement
            "project\nname",  # Control character (newline)
            "project\tname",  # Control character (tab)
        ],
    )
    def test_project_generation_with_invalid_names(self, invalid_project_name):
        with runner.isolated_filesystem():
            args = ["new", invalid_project_name]
            result = runner.invoke(app, args)
            assert result.exit_code != 0
            assert result.exception.args[0] == "Invalid project name"
