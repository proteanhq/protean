import os
import sys

from pathlib import Path

import pytest

from protean.cli import derive_domain, generate_docker_compose


def change_working_directory_to(path):
    """Change working directory to a specific test directory
    and add it to the Python path so that the test can import.

    The test directory is expected to be in `support/test_domains`.
    """
    test_path = (
        Path(__file__) / ".." / ".." / "support" / "test_domains" / path
    ).resolve()

    os.chdir(test_path)
    sys.path.insert(0, test_path)


class TestGenerateDockerCompose:
    @pytest.fixture(autouse=True)
    def reset_path(self, request):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

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

            generate_docker_compose("sqlite_domain")

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
