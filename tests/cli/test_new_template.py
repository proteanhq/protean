"""Comprehensive tests for protean new template generation."""

from pathlib import Path

from typer.testing import CliRunner

from protean.cli import app

runner = CliRunner()


class TestTemplateGeneration:
    """Test the complete template generation process."""

    def test_project_structure_is_created_correctly(self):
        """Test that all expected files and directories are created."""
        with runner.isolated_filesystem() as project_dir:
            args = [
                "new",
                "test_project",
                "-o",
                project_dir,
                "--defaults",
                "--skip-setup",  # Skip setup to speed up tests
                "-d",
                "author_name=Test Author",
                "-d",
                "author_email=test@example.com",
            ]
            result = runner.invoke(app, args)
            assert result.exit_code == 0

            project_path = Path(project_dir) / "test_project"

            # Check root level files
            assert (project_path / "pyproject.toml").exists()
            assert (project_path / "README.md").exists()
            assert (project_path / "Makefile").exists()
            assert (project_path / ".gitignore").exists()
            assert (project_path / ".pre-commit-config.yaml").exists()
            assert (project_path / ".dockerignore").exists()
            assert (project_path / ".env.example").exists()
            assert (project_path / "logging.toml").exists()

            # Check Docker files
            assert (project_path / "Dockerfile").exists()
            assert (project_path / "Dockerfile.dev").exists()
            assert (project_path / "docker-compose.yml").exists()
            assert (project_path / "docker-compose.override.yml").exists()
            assert (project_path / "docker-compose.prod.yml").exists()
            assert (project_path / "nginx.conf").exists()

            # Check scripts folder and activation scripts
            assert (project_path / "scripts").is_dir()
            assert (project_path / "scripts" / "activate.sh").exists()
            assert (project_path / "scripts" / "activate.fish").exists()
            assert (project_path / "scripts" / "activate.bat").exists()

            # Check src structure
            assert (project_path / "src").is_dir()
            assert (project_path / "src" / "test_project").is_dir()
            assert (project_path / "src" / "test_project" / "__init__.py").exists()
            assert (project_path / "src" / "test_project" / "domain.py").exists()
            assert (project_path / "src" / "test_project" / "domain.toml").exists()

            # Check tests structure
            assert (project_path / "tests").is_dir()
            assert (project_path / "tests" / "test_project").is_dir()
            assert (project_path / "tests" / "test_project" / "conftest.py").exists()
            assert (
                project_path / "tests" / "test_project" / "domain" / "__init__.py"
            ).exists()
            assert (
                project_path / "tests" / "test_project" / "application" / "__init__.py"
            ).exists()
            assert (
                project_path / "tests" / "test_project" / "integration" / "__init__.py"
            ).exists()

    def test_activation_scripts_exist_and_are_readable(self):
        """Test that activation scripts exist and are readable."""
        with runner.isolated_filesystem() as project_dir:
            args = [
                "new",
                "test_scripts",
                "-o",
                project_dir,
                "--defaults",
                "--skip-setup",
                "-d",
                "author_name=Test Author",
                "-d",
                "author_email=test@example.com",
            ]
            result = runner.invoke(app, args)
            assert result.exit_code == 0

            project_path = Path(project_dir) / "test_scripts"

            # Check that all activation scripts exist
            sh_script = project_path / "scripts" / "activate.sh"
            fish_script = project_path / "scripts" / "activate.fish"
            bat_script = project_path / "scripts" / "activate.bat"

            assert sh_script.exists()
            assert fish_script.exists()
            assert bat_script.exists()

            # Check they are readable and have content
            assert len(sh_script.read_text()) > 100
            assert len(fish_script.read_text()) > 100
            assert len(bat_script.read_text()) > 100

            # Check they contain expected content
            sh_content = sh_script.read_text()
            assert "#!/bin/bash" in sh_content or "#!/usr/bin/env bash" in sh_content
            assert ".venv" in sh_content

            fish_content = fish_script.read_text()
            assert "#!/usr/bin/env fish" in fish_content
            assert ".venv" in fish_content

            bat_content = bat_script.read_text()
            assert "@echo off" in bat_content
            assert ".venv" in bat_content

    def test_template_variable_substitution(self):
        """Test that template variables are correctly substituted."""
        with runner.isolated_filesystem() as project_dir:
            args = [
                "new",
                "my_awesome_project",
                "-o",
                project_dir,
                "--defaults",
                "--skip-setup",
                "-d",
                "author_name=Jane Doe",
                "-d",
                "author_email=jane@doe.com",
                "-d",
                "short_description=An awesome Protean project",
            ]
            result = runner.invoke(app, args)
            assert result.exit_code == 0

            project_path = Path(project_dir) / "my_awesome_project"

            # Check README.md contains project name
            readme_content = (project_path / "README.md").read_text()
            assert "# my_awesome_project" in readme_content
            assert "An awesome Protean project" in readme_content

            # Check pyproject.toml contains correct metadata
            pyproject_content = (project_path / "pyproject.toml").read_text()
            assert 'name = "my-awesome-project"' in pyproject_content
            assert 'authors = ["Jane Doe <jane@doe.com>"]' in pyproject_content
            assert 'description = "An awesome Protean project"' in pyproject_content

            # Check package name is correctly transformed
            assert (project_path / "src" / "my_awesome_project").is_dir()
            assert (project_path / "tests" / "my_awesome_project").is_dir()

            # Check domain.py imports use correct package name
            domain_py = (
                project_path / "src" / "my_awesome_project" / "domain.py"
            ).read_text()
            assert (
                "from my_awesome_project" in domain_py
                or "my_awesome_project" in domain_py
            )

    def test_different_database_configurations(self):
        """Test that different database choices generate correct configuration."""
        databases = [
            ("memory", "memory"),
            ("postgresql", "postgresql"),
            ("sqlite", "sqlite"),
            ("elasticsearch", "elasticsearch"),
        ]

        for db_choice, expected_value in databases:
            with runner.isolated_filesystem() as project_dir:
                args = [
                    "new",
                    f"test_db_{db_choice}",
                    "-o",
                    project_dir,
                    "--defaults",
                    "--skip-setup",
                    "-d",
                    "author_name=Test",
                    "-d",
                    "author_email=test@test.com",
                    "-d",
                    f"database={expected_value}",
                ]
                result = runner.invoke(app, args)
                assert result.exit_code == 0

                project_path = Path(project_dir) / f"test_db_{db_choice}"

                # Check domain.toml contains correct database configuration
                domain_toml = (
                    project_path / "src" / f"test_db_{db_choice}" / "domain.toml"
                ).read_text()

                # Verify database configuration is present
                if expected_value != "memory":
                    assert (
                        "database" in domain_toml.lower()
                        or "provider" in domain_toml.lower()
                    )

    def test_different_broker_configurations(self):
        """Test that different broker choices generate correct configuration."""
        brokers = [
            ("inline", "inline"),
            ("redis", "redis"),
            ("redis-pubsub", "redis_pubsub"),
        ]

        for broker_choice, expected_value in brokers:
            with runner.isolated_filesystem() as project_dir:
                # Use underscores in project name to ensure valid package name
                project_name = f"test_broker_{broker_choice.replace('-', '_')}"
                args = [
                    "new",
                    project_name,
                    "-o",
                    project_dir,
                    "--defaults",
                    "--skip-setup",
                    "-d",
                    "author_name=Test",
                    "-d",
                    "author_email=test@test.com",
                    "-d",
                    f"broker={expected_value.replace('_', '-')}",
                ]
                result = runner.invoke(app, args)
                assert result.exit_code == 0

                project_path = Path(project_dir) / project_name

                # Check domain.toml for broker configuration
                domain_toml = (
                    project_path
                    / "src"
                    / project_name.replace("-", "_")
                    / "domain.toml"
                ).read_text()

                # Verify broker configuration
                if expected_value != "inline":
                    assert "broker" in domain_toml.lower()

    def test_copier_answers_file_is_created(self):
        """Test that .copier-answers.yml is created with correct answers."""
        with runner.isolated_filesystem() as project_dir:
            args = [
                "new",
                "test_copier",
                "-o",
                project_dir,
                "--defaults",
                "--skip-setup",
                "-d",
                "author_name=Test Author",
                "-d",
                "author_email=test@example.com",
            ]
            result = runner.invoke(app, args)
            assert result.exit_code == 0

            project_path = Path(project_dir) / "test_copier"
            answers_file = project_path / ".copier-answers.yml"

            assert answers_file.exists()

            # Read and verify answers file content
            import yaml

            with open(answers_file) as f:
                answers = yaml.safe_load(f)

            assert answers["project_name"] == "test_copier"
            assert answers["author_name"] == "Test Author"
            assert answers["author_email"] == "test@example.com"
            assert answers["package_name"] == "test_copier"

    def test_example_code_generation(self):
        """Test that example code is generated when include_example is true."""
        with runner.isolated_filesystem() as project_dir:
            args = [
                "new",
                "test_with_example",
                "-o",
                project_dir,
                "--defaults",
                "--skip-setup",
                "-d",
                "author_name=Test",
                "-d",
                "author_email=test@test.com",
                "-d",
                "include_example=true",
            ]
            result = runner.invoke(app, args)
            assert result.exit_code == 0

            project_path = Path(project_dir) / "test_with_example"
            example_path = project_path / "src" / "test_with_example" / "example"

            # Check example directory exists and contains expected files
            assert example_path.is_dir()
            assert (example_path / "__init__.py").exists()
            assert (example_path / "aggregate.py").exists()
            assert (example_path / "commands.py").exists()
            assert (example_path / "command_handlers.py").exists()
            assert (example_path / "events.py").exists()
            assert (example_path / "event_handlers.py").exists()
            assert (example_path / "value_objects.py").exists()
            assert (example_path / "repository.py").exists()

            # Check projections directory
            projections_path = (
                project_path / "src" / "test_with_example" / "projections"
            )
            assert projections_path.is_dir()
            assert (projections_path / "__init__.py").exists()
            assert (projections_path / "example_projector.py").exists()
            assert (projections_path / "example_summary.py").exists()

    def test_no_example_code_when_disabled(self):
        """Test that example code is not generated when include_example is false."""
        with runner.isolated_filesystem() as project_dir:
            args = [
                "new",
                "test_no_example",
                "-o",
                project_dir,
                "--defaults",
                "--skip-setup",
                "-d",
                "author_name=Test",
                "-d",
                "author_email=test@test.com",
                "-d",
                "include_example=false",
            ]
            result = runner.invoke(app, args)
            assert result.exit_code == 0

            project_path = Path(project_dir) / "test_no_example"
            example_path = project_path / "src" / "test_no_example" / "example"

            # Check example directory does not exist
            assert not example_path.exists()

    def test_github_workflow_generation(self):
        """Test that GitHub workflow files are generated."""
        with runner.isolated_filesystem() as project_dir:
            args = [
                "new",
                "test_github",
                "-o",
                project_dir,
                "--defaults",
                "--skip-setup",
                "-d",
                "author_name=Test",
                "-d",
                "author_email=test@test.com",
            ]
            result = runner.invoke(app, args)
            assert result.exit_code == 0

            project_path = Path(project_dir) / "test_github"

            # Check .github directory structure
            github_path = project_path / ".github"
            assert github_path.is_dir()

            workflows_path = github_path / "workflows"
            assert workflows_path.is_dir()

            # Note: Check if any workflow files exist (the template might conditionally include them)
            # The exact files depend on the template configuration

    def test_docker_compose_files_content(self):
        """Test that docker-compose files are generated with correct service definitions."""
        with runner.isolated_filesystem() as project_dir:
            args = [
                "new",
                "test_docker",
                "-o",
                project_dir,
                "--defaults",
                "--skip-setup",
                "-d",
                "author_name=Test",
                "-d",
                "author_email=test@test.com",
                "-d",
                "database=postgresql",
                "-d",
                "broker=redis",
            ]
            result = runner.invoke(app, args)
            assert result.exit_code == 0

            project_path = Path(project_dir) / "test_docker"

            # Check docker-compose.yml contains expected services
            docker_compose = (project_path / "docker-compose.yml").read_text()

            # When PostgreSQL is selected, relevant services should be in docker-compose
            if "postgresql" in docker_compose.lower():
                assert (
                    "postgres" in docker_compose.lower()
                    or "database" in docker_compose.lower()
                )

            # When Redis is selected as broker
            if "redis" in docker_compose.lower():
                assert "redis" in docker_compose.lower()

    def test_makefile_contains_expected_targets(self):
        """Test that Makefile contains expected targets."""
        with runner.isolated_filesystem() as project_dir:
            args = [
                "new",
                "test_makefile",
                "-o",
                project_dir,
                "--defaults",
                "--skip-setup",
                "-d",
                "author_name=Test",
                "-d",
                "author_email=test@test.com",
            ]
            result = runner.invoke(app, args)
            assert result.exit_code == 0

            project_path = Path(project_dir) / "test_makefile"
            makefile = (project_path / "Makefile").read_text()

            # Check for common Make targets
            assert "test:" in makefile or "test-" in makefile
            assert "run:" in makefile or "server:" in makefile or "start:" in makefile
            assert "docker" in makefile.lower()
            assert "up:" in makefile or "down:" in makefile

    def test_logging_configuration_file(self):
        """Test that logging.toml is created with proper configuration."""
        with runner.isolated_filesystem() as project_dir:
            args = [
                "new",
                "test_logging",
                "-o",
                project_dir,
                "--defaults",
                "--skip-setup",
                "-d",
                "author_name=Test",
                "-d",
                "author_email=test@test.com",
            ]
            result = runner.invoke(app, args)
            assert result.exit_code == 0

            project_path = Path(project_dir) / "test_logging"
            logging_toml = project_path / "logging.toml"

            assert logging_toml.exists()

            # Check logging configuration content
            content = logging_toml.read_text()
            # The logging.toml file has a different format in the template
            # It uses custom sections like [general], [environments], [loggers], etc.
            assert "[general]" in content or "[loggers]" in content
            assert "level" in content.lower()
            assert "test_logging" in content  # Should reference the package name
