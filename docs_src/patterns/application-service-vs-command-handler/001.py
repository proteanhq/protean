from protean import Domain

domain = Domain(name="ApplicationServiceRegistration")

# --8<-- [start:user_service]
import hashlib
from datetime import UTC, datetime

from protean import current_domain
from protean.core.application_service import BaseApplicationService, use_case
from protean.core.event import BaseEvent
from protean.fields import Auto, DateTime, Identifier, String

# --- Domain elements ---


@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    email: String(required=True, max_length=255)
    name: String(required=True, max_length=100)
    password_hash: String(max_length=255)
    status: String(default="pending")
    registered_at: DateTime()

    def register(self, password: str) -> None:
        """Complete the registration process."""
        self.password_hash = self._hash_password(password)
        self.status = "active"
        self.registered_at = datetime.now(UTC)

        self.raise_(
            UserRegistered(
                user_id=self.user_id,
                email=self.email,
                name=self.name,
            )
        )

    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()


@domain.event(part_of=User)
class UserRegistered(BaseEvent):
    user_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True)


# --- Application Service ---


@domain.application_service(part_of=User)
class UserService(BaseApplicationService):
    @use_case
    def register_user(self, email: str, name: str, password: str) -> User:
        """Register a new user and return the created user.

        The @use_case decorator wraps this method in a UnitOfWork,
        so the aggregate is persisted and events are published
        automatically when the method returns.
        """
        repo = current_domain.repository_for(User)
        user = User(email=email, name=name)
        user.register(password)
        repo.add(user)
        return user  # (1)


# --8<-- [end:user_service]

domain.init(traverse=False)

from fastapi import FastAPI
from pydantic import BaseModel

from protean.integrations.fastapi import DomainContextMiddleware

app = FastAPI()
app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})


class CreateUserRequest(BaseModel):
    email: str
    name: str
    password: str


# --8<-- [start:endpoint]
@app.post("/users", status_code=201)
def create_user(payload: CreateUserRequest):
    service = UserService()
    user = service.register_user(
        email=payload.email,
        name=payload.name,
        password=payload.password,
    )
    return {
        "id": str(user.user_id),
        "email": user.email,
        "name": user.name,
        "status": user.status,
    }


# --8<-- [end:endpoint]
