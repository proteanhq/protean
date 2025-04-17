import logging
from unittest.mock import MagicMock, call, patch

import pytest
from click.exceptions import Abort
from fastapi.testclient import TestClient

from protean.server.fastapi_server import ProteanFastAPIServer, create_app, logger


class TestServerStartup:
    """Test suite for server startup and accessibility."""

    @pytest.fixture
    def client(self, test_domain):
        """Create a test client for the FastAPI app."""
        server = ProteanFastAPIServer(domain=test_domain)
        return TestClient(server.app)

    @pytest.mark.fastapi
    def test_server_creation(self, test_domain):
        """Test that the server can be created."""
        server = ProteanFastAPIServer(domain=test_domain)
        assert server is not None
        assert server.app is not None
        assert server.domain is not None
        assert server.domain.name == test_domain.name

    @pytest.mark.fastapi
    def test_server_root_endpoint(self, client, test_domain):
        """Test that the server's root endpoint is accessible and returns the expected data."""
        response = client.get("/")
        assert response.status_code == 200

        # Verify response structure
        data = response.json()
        assert data["status"] == "success"
        assert "message" in data
        assert test_domain.name in data["message"]

        # Verify domain data
        assert "data" in data
        assert "domain" in data["data"]
        assert data["data"]["domain"]["name"] == test_domain.name
        assert data["data"]["domain"]["normalized_name"] == test_domain.normalized_name

    @pytest.mark.fastapi
    def test_create_app_factory(self, test_domain):
        """Test the create_app factory function."""
        app = create_app(test_domain)
        assert app is not None

        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200

    @pytest.mark.fastapi
    def test_cors_origins_configuration(self, test_domain):
        """Test that CORS origins are properly configured."""
        # Test with default origins
        server = ProteanFastAPIServer(domain=test_domain)
        cors_middleware = next(
            (m for m in server.app.user_middleware if "CORSMiddleware" in str(m.cls)),
            None,
        )
        assert cors_middleware is not None
        assert cors_middleware.kwargs["allow_origins"] == ["*"]

        # Test with custom origins
        custom_origins = ["http://localhost:3000", "https://example.com"]
        server = ProteanFastAPIServer(domain=test_domain, cors_origins=custom_origins)
        cors_middleware = next(
            (m for m in server.app.user_middleware if "CORSMiddleware" in str(m.cls)),
            None,
        )
        assert cors_middleware is not None
        assert cors_middleware.kwargs["allow_origins"] == custom_origins

        # Test with CORS disabled
        server = ProteanFastAPIServer(domain=test_domain, enable_cors=False)
        cors_middleware = next(
            (m for m in server.app.user_middleware if "CORSMiddleware" in str(m.cls)),
            None,
        )
        assert cors_middleware is None

    @pytest.mark.fastapi
    def test_debug_mode_configuration(self, test_domain):
        """Test that debug mode is properly configured."""
        # Test with debug mode disabled (default)
        server = ProteanFastAPIServer(domain=test_domain)
        assert server.debug is False
        assert logger.level == logging.INFO

        # Test with debug mode enabled
        server = ProteanFastAPIServer(domain=test_domain, debug=True)
        assert server.debug is True
        assert logger.level == logging.DEBUG

    @pytest.mark.fastapi
    @patch("protean.server.fastapi_server.uvicorn.run")
    def test_server_run_method(self, mock_uvicorn_run, test_domain):
        """Test the server's run method with different configurations."""
        # Test with default host and port
        server = ProteanFastAPIServer(domain=test_domain)
        server.run()
        mock_uvicorn_run.assert_called_once_with(server.app, host="0.0.0.0", port=8000)
        mock_uvicorn_run.reset_mock()

        # Test with custom host and port
        server.run(host="127.0.0.1", port=5000)
        mock_uvicorn_run.assert_called_once_with(
            server.app, host="127.0.0.1", port=5000
        )
        mock_uvicorn_run.reset_mock()

        # Test with debug mode enabled
        server = ProteanFastAPIServer(domain=test_domain, debug=True)
        server.run()
        mock_uvicorn_run.assert_called_once_with(server.app, host="0.0.0.0", port=8000)
        mock_uvicorn_run.reset_mock()

        # Test with CORS disabled
        server = ProteanFastAPIServer(domain=test_domain, enable_cors=False)
        server.run()
        mock_uvicorn_run.assert_called_once_with(server.app, host="0.0.0.0", port=8000)
        mock_uvicorn_run.reset_mock()

        # Test with custom CORS origins
        server = ProteanFastAPIServer(
            domain=test_domain, cors_origins=["http://localhost:3000"]
        )
        server.run()
        mock_uvicorn_run.assert_called_once_with(server.app, host="0.0.0.0", port=8000)

    @pytest.mark.fastapi
    @patch("protean.cli.server2.derive_domain")
    @patch("protean.cli.server2.ProteanFastAPIServer")
    def test_server_command_with_subcommand(self, mock_server, mock_derive_domain):
        """Test that the server command exits early when a subcommand is invoked."""
        from protean.cli.server2 import main

        # Create a mock context with an invoked subcommand
        mock_ctx = MagicMock()
        mock_ctx.invoked_subcommand = "subcommand"

        # Call the main function with the mock context
        main(mock_ctx)

        # Verify that neither derive_domain nor ProteanFastAPIServer were called
        mock_derive_domain.assert_not_called()
        mock_server.assert_not_called()

    @pytest.mark.fastapi
    @patch("protean.cli.server2.derive_domain")
    @patch("protean.cli.server2.ProteanFastAPIServer")
    @patch("protean.cli.server2.typer.echo")
    @patch("protean.cli.server2.logger.error")
    def test_server_command_exception_handling(
        self, mock_logger_error, mock_echo, mock_server, mock_derive_domain
    ):
        """Test that the server command properly handles and reports exceptions."""
        from protean.cli.server2 import main

        # Set up the mock server to raise an exception
        mock_server_instance = mock_server.return_value
        mock_server_instance.run.side_effect = Exception("Test error")

        # Create a mock context
        mock_ctx = MagicMock()
        mock_ctx.invoked_subcommand = None

        # Call the main function and expect it to raise click.exceptions.Abort
        with pytest.raises(Abort):
            main(mock_ctx)

        # Verify that the error was logged
        mock_logger_error.assert_called_once_with("Error starting server: Test error")

        # Verify both echo messages in the correct order
        assert mock_echo.call_count == 2
        mock_echo.assert_has_calls(
            [
                call("Starting Protean FastAPI server at 0.0.0.0:8000..."),
                call("Error starting server: Test error", err=True),
            ]
        )
