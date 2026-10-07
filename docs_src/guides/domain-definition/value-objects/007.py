from protean import Domain
from protean.fields import String

domain = Domain(name="Profiles")


# --8<-- [start:replace]
@domain.value_object
class Profile:
    name: String(max_length=50, required=True)
    nickname: String(max_length=50)


profile = Profile(name="Alice", nickname="Ali")
updated = profile.replace(nickname=None)

assert updated.nickname is None  # explicitly set to None
# --8<-- [end:replace]
