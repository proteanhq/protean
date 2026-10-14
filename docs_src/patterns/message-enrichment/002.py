# --8<-- [start:middleware]
# middleware.py -- FastAPI middleware that sets tenant context

from uuid import uuid4

from protean.utils.globals import g


class TenantContextMiddleware:
    """Extract tenant_id from the auth token and store it in g."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Extract tenant from auth header (simplified)
            headers = dict(scope.get("headers", []))
            token = headers.get(b"authorization", b"").decode()
            tenant_id = decode_tenant_from_token(token)
            user_id = decode_user_from_token(token)

            g.tenant_id = tenant_id
            g.user_id = user_id
            g.request_id = headers.get(b"x-request-id", b"").decode() or str(uuid4())

        await self.app(scope, receive, send)


# --8<-- [end:middleware]


# A stand-in token format, "<tenant>:<user>", in place of a real auth library.
def decode_tenant_from_token(token: str) -> str:
    return token.split(":")[0]


def decode_user_from_token(token: str) -> str:
    return token.split(":")[1]
