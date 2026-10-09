from protean import Domain

domain = Domain(name="Access")


class PermissionDenied(Exception):
    pass


# --8<-- [start:security]
from protean.integrations.logging import (
    SECURITY_EVENT_VALIDATION_FAILED,
    log_security_event,
)


def check_admin_access(user, resource):
    if not user.can_access(resource):
        log_security_event(
            SECURITY_EVENT_VALIDATION_FAILED,
            aggregate="Resource",
            aggregate_id=resource.id,
            user_id=user.id,
            reason="not_authorized",
        )
        raise PermissionDenied()


# --8<-- [end:security]
