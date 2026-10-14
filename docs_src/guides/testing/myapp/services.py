from myapp import domain
from myapp.models import User
from protean import use_case
from protean.utils.globals import current_domain


@domain.application_service(part_of=User)
class UserApplicationServices:
    @use_case
    def register_user(self, email, name):
        user = User(email=email, name=name)
        current_domain.repository_for(User).add(user)
        return user.id

    @use_case
    def activate_user(self, user_id):
        repo = current_domain.repository_for(User)
        user = repo.get(user_id)
        user.activate()
        repo.add(user)
