import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import derive_domain
from protean.cli.generate import app, docker_compose
from tests.shared import change_working_directory_to

runner = CliRunner()


class TestGenerateDockerCompose:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_cli_command(self):
        """Test the CLI command to generate a docker compose file"""
        change_working_directory_to("test8")
        # Ensure no pre-existing docker-compose.yml
        compose_file = Path("docker-compose.yml")
        if compose_file.exists(): compose_file.unlink()

        args = ["docker-compose", "--domain", "sqlite_domain.py"]
        result = runner.invoke(app, args)

        print(result.output)
        assert result.exit_code == 0

        assert Path("docker-compose.yml").exists()
        assert Path("docker-compose.yml").is_file()

    def test_abort_on_existing_file(self):
        """Should exit non-zero and leave file untouched if docker-compose.yml exists."""
        change_working_directory_to("test8")
        # Create an existing compose file
        Path("docker-compose.yml").write_text("DO NOT OVERWRITE")

        args = ["docker-compose", "--domain", "sqlite_domain.py"]
        result = runner.invoke(app, args)

        # Expect a non-zero exit code and no overwrite
        assert result.exit_code != 0
        assert Path("docker-compose.yml").read_text() == "DO NOT OVERWRITE"

    class TestGenerateSqliteService:
        def test_correct_config_is_loaded(self):
            """Test that the correct configuration is loaded for SQLite database"""
            change_working_directory_to("test8")

            domain = derive_domain("sqlite_domain")
            assert domain is not None
            assert domain.name == "SQLite-Domain"
            assert domain.providers["default"].conn_info["provider"] == "sqlite"
            assert domain.providers["default"]._engine.url.database == ":memory:"
            assert domain.providers["default"]._engine.url.drivername == "sqlite"

        def test_docker_compose_is_generated(self):
            """Test that the docker-compose.yml file is generated for SQLite database"""
            change_working_directory_to("test8")
            # Ensure no pre-existing docker-compose.yml
            compose_file = Path("docker-compose.yml")
            if compose_file.exists(): compose_file.unlink()

            docker_compose("sqlite_domain")

            assert Path("docker-compose.yml").exists()
            assert Path("docker-compose.yml").is_file()

            with open("docker-compose.yml", "r") as f:
                content = f.read()
                assert "version: '3'" in content
                assert "services:" in content
                assert "sqlite" in content
                assert "image:" in content
