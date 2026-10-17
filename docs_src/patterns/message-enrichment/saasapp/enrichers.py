# --8<-- [start:functions]
# enrichers.py -- reusable enrichers for multiple domains

from protean.utils.globals import g


def tenant_enricher(event, aggregate):
    return {"tenant_id": getattr(g, "tenant_id", None)}


def audit_enricher(event, aggregate):
    return {
        "user_id": getattr(g, "user_id", None),
        "request_id": getattr(g, "request_id", None),
    }


def tenant_command_enricher(command):
    return {"tenant_id": getattr(g, "tenant_id", None)}


# --8<-- [end:functions]
