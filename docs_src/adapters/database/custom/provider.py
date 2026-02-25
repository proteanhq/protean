# --8<-- [start:full]
from protean.port.provider import BaseProvider, DatabaseCapabilities, ProviderRegistry


class DynamoDBProvider(BaseProvider):
    """Custom DynamoDB database provider."""

    @property
    def capabilities(self) -> DatabaseCapabilities:
        return (
            DatabaseCapabilities.CRUD
            | DatabaseCapabilities.FILTER
            | DatabaseCapabilities.BULK_OPERATIONS
            | DatabaseCapabilities.ORDERING
        )

    def get_session(self):
        """Return a session-like wrapper around a DynamoDB client."""
        ...

    def get_connection(self):
        """Return the underlying boto3 DynamoDB resource."""
        ...

    def is_alive(self) -> bool:
        """Check connectivity to DynamoDB."""
        ...

    def decorate_model_class(self, entity_cls, model_cls):
        """Create DynamoDB table definition from model class."""
        ...

    def get_dao(self, entity_cls, model_cls):
        """Return a DAO instance for the given entity."""
        ...


def register():
    """Entry point called by Protean on first access."""
    ProviderRegistry.register(
        "dynamodb",
        "mypackage.adapters.dynamodb:DynamoDBProvider",
    )


# --8<-- [end:full]
