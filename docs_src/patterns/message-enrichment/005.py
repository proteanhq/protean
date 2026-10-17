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

from protean import handle
from protean.fields import Auto, Identifier

# isort: split

# --8<-- [start:registration]
# domain.py -- register the enrichers from enrichers.py
from protean import Domain

domain = Domain(name="SaasApp")
domain.register_event_enricher(tenant_enricher)
domain.register_event_enricher(audit_enricher)
domain.register_command_enricher(tenant_command_enricher)
# --8<-- [end:registration]

domain.config["command_processing"] = "sync"


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)

    def cancel(self):
        self.raise_(OrderCancelled(order_id=self.order_id))


@domain.event(part_of=Order)
class OrderCancelled:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class CancelOrder:
    order_id: Identifier(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(CancelOrder)
    def cancel(self, command: CancelOrder):
        command_tenants.append(g.message_in_context.metadata.extensions)


command_tenants = []
