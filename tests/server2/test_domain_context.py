import pytest
from fastapi.testclient import TestClient

from protean.domain import Domain
from protean.server.fastapi_server import ProteanFastAPIServer
from protean.utils.globals import g


@pytest.mark.no_test_domain
class TestDomainContext:
    """Test suite for domain context availability during requests."""

    @pytest.fixture
    def custom_domain(self):
        domain = Domain(__file__, "Custom Domain Context Test")
        domain._initialize()

        yield domain

    @pytest.fixture
    def test_route_app(self, custom_domain):
        """Create a FastAPI app with routes that test domain context availability."""
        server = ProteanFastAPIServer(domain=custom_domain)

        # Add routes to test domain context
        @server.app.get("/context")
        async def get_domain_context():
            """Return the domain name from the current context."""
            # The domain context should be available from the middleware.
            #   We are using the `g` proxy object to verify that the domain context is available.
            return {"g-class": repr(g)}

        return server.app

    @pytest.fixture
    def client(self, test_route_app):
        """Create a test client for the FastAPI app."""
        return TestClient(test_route_app)

    @pytest.mark.fastapi
    def test_domain_variables_are_accessible(self, client, custom_domain):
        # Call the test route that returns the domain context.
        response = client.get("/context")

        assert response.status_code == 200
        assert (
            response.json()["g-class"] == "<protean.g of 'Custom Domain Context Test'>"
        )

    @pytest.mark.fastapi
    def test_domain_context_is_set_for_each_request(self, custom_domain):
        """Test that middleware enters domain context for each request."""
        # Create app and client
        server = ProteanFastAPIServer(domain=custom_domain)
        client = TestClient(server.app)

        # Make a request
        response = client.get("/")

        assert response.status_code == 200

    @pytest.mark.fastapi
    def test_domain_context_middleware(self, custom_domain):
        """Test that domain context middleware is properly set up."""
        server = ProteanFastAPIServer(domain=custom_domain)

        # Find domain context middleware in app
        domain_context_middleware_present = False
        for middleware in server.app.user_middleware:
            # The middleware is a function, so it's signature looks like this:
            #   '<function ProteanFastAPIServer._setup_middleware.<locals>.domain_context_middleware at ..>'
            if "domain_context_middleware" in str(middleware.kwargs["dispatch"]):
                domain_context_middleware_present = True
                break

        assert domain_context_middleware_present, "Domain context middleware not found"

    @pytest.mark.fastapi
    def test_cors_enabled(self, custom_domain):
        """Test that CORS is enabled by default."""
        server = ProteanFastAPIServer(domain=custom_domain)

        # Check that CORS middleware is among the registered middleware
        cors_middleware_present = False

        # Iterate through middleware to find CORS middleware
        for middleware in server.app.user_middleware:
            if "CORSMiddleware" in str(middleware.cls):
                cors_middleware_present = True
                break

        assert cors_middleware_present
