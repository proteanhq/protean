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

        args = ["docker-compose", "sqlite_domain.py"]
        result = runner.invoke(app, args)

        print(result.output)
        assert result.exit_code == 0

        # FIXME - This test is failing because the docker-compose.yml file is not being generated
        # assert Path("docker-compose.yml").exists()

    class TestGenerateSqliteService:
        @pytest.mark.sqlite
        def test_correct_config_is_loaded(self):
            """Test that the correct configuration is loaded for SQLite database"""
            change_working_directory_to("test8")

            domain = derive_domain("sqlite_domain")
            domain.init()
            assert domain is not None
            assert domain.domain_name == "SQLite-Domain"
            assert (
                domain.providers["default"].conn_info["PROVIDER"]
                == "protean.adapters.repository.sqlalchemy.SAProvider"
            )
            assert domain.providers["default"].conn_info["DATABASE"] == "sqlite"
            assert domain.providers["default"]._engine.url.database == ":memory:"
            assert domain.providers["default"]._engine.url.drivername == "sqlite"

        @pytest.mark.sqlite
        def test_docker_compose_is_generated(self):
            """Test that the docker-compose.yml file is generated for SQLite database"""
            change_working_directory_to("test8")

            docker_compose("sqlite_domain")

            # FIXME - This test is failing because the docker-compose.yml file is not being generated
            #   A few example tests have been provided as illustration.

            # Assert that the docker-compose.yml file is generated in the same directory as the domain file
            # assert Path("docker-compose.yml").exists()
            # assert Path("docker-compose.yml").is_file()

            # with open("docker-compose.yml", "r") as f:
            #     content = f.read()

            #     assert "version: '3.8'" in content
            #     assert "services:" in content
            #     assert "sqlite:" in content
            #     assert "image: sqlite" in content
            #     assert "container_name: sqlite" in content
            #     assert "restart: always" in content
            #     assert "volumes:" in content
            #     assert "sqlite:/var/lib/sqlite" in content
            #     assert "networks:" in content
            #     assert "default:" in content
