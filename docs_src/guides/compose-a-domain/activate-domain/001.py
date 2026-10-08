from protean import Domain, current_domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class User:
    name: String(max_length=50)


domain.init(traverse=False)

# --8<-- [start:manual]
context = domain.domain_context()

# Activate the domain
context.push()

# Do something interesting
user_repo = current_domain.repository_for(User)

# Reset domain stack when done
context.pop()
# --8<-- [end:manual]
