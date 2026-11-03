"""Events that ``unraised_event_domain.Journal`` imports inside its methods.

They live apart from ``Journal`` so its module binds none of their names at
module level.
"""

from protean.core.event import BaseEvent
from protean.fields import Identifier


class Voided(BaseEvent):
    journal_id = Identifier()


class Reversed(BaseEvent):
    journal_id = Identifier()


class Archived(BaseEvent):
    journal_id = Identifier()


class Flagged(BaseEvent):
    journal_id = Identifier()
