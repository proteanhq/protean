# --8<-- [start:elements]
from protean import Domain
from protean.core.projector import on
from protean.fields import Identifier, String

domain = Domain(name="Accounts")


@domain.aggregate
class User:
    email: String(required=True)
    name: String(required=True)


@domain.event(part_of=User)
class UserRegistered:
    user_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True)


@domain.projection
class UserProfile:
    user_id: Identifier(identifier=True)
    email: String()
    name: String()


# --8<-- [end:elements]


# --8<-- [start:projector]
from protean import current_domain
from protean.exceptions import ObjectNotFoundError


@domain.projector(projector_for=UserProfile, aggregates=[User])
class UserProfileProjector:
    @on(UserRegistered)
    def on_user_registered(self, event: UserRegistered):
        repository = current_domain.repository_for(UserProfile)

        # Check if profile already exists
        try:
            repository.get(event.user_id)
            # Profile already exists, skip creation
            return
        except ObjectNotFoundError:
            pass  # Expected case - create new profile

        profile = UserProfile(user_id=event.user_id, email=event.email, name=event.name)
        repository.add(profile)


# --8<-- [end:projector]
