"""
Command enricher: attach request context to every command.

This example demonstrates:
- Registering a command enricher with @domain.command_enricher
- The enricher signature: def fn(command) -> dict
- Reading cross-cutting context from g and returning it for metadata.extensions
- Safe context access with getattr(..., None) so a missing value never aborts

Usage:
    g.request_id = "req-1"
    domain.process(RegisterUser(...), asynchronous=False)
    # the enricher merges request context into the command's metadata.extensions
"""

from protean import Domain, current_domain, handle
from protean.fields import Identifier, String
from protean.utils.globals import g

# Domain setup
domain = Domain()


@domain.aggregate
class User:
    user_id: Identifier(identifier=True)
    email: String(required=True)


@domain.command(part_of="User")
class RegisterUser:
    user_id: Identifier(required=True)
    email: String(required=True)


@domain.command_handler(part_of=User)
class UserCommandHandler:
    @handle(RegisterUser)
    def register(self, command: RegisterUser):
        user = User(user_id=command.user_id, email=command.email)
        current_domain.repository_for(User).add(user)


@domain.command_enricher
def add_request_context(command):
    """Merge request/tenant context into every command's metadata.extensions."""
    return {
        "request_id": getattr(g, "request_id", None),
        "tenant_id": getattr(g, "tenant_id", None),
    }


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        g.request_id = "req-1"
        g.tenant_id = "acme"
        domain.process(
            RegisterUser(user_id="U-1", email="user@example.com"),
            asynchronous=False,
        )
        print("command processed; request/tenant context merged into extensions")
