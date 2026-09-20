"""
Projection with configuration options: schema_name, order_by, limit, and cache.

This example demonstrates:
- Custom schema_name for database table naming
- Custom order_by for default query ordering
- Custom limit for query result limits
- Cache-backed projection (cache overrides provider)
- Abstract projection as a base class
- Projection options are passed via decorator or domain.register()

Usage:
    user = UserDirectory(
        user_id="USR-001", first_name="Alice",
        last_name="Smith", email="alice@example.com",
    )
    domain.repository_for(UserDirectory).add(user)
"""

from protean import Domain
from protean.fields import Identifier, Integer, String

# Domain setup
domain = Domain()


@domain.projection(schema_name="user_directory_view", order_by=("last_name",), limit=50)
class UserDirectory:
    """Projection with custom schema, ordering, and limit.

    - schema_name: Controls the database table name
    - order_by: Default ordering for queries
    - limit: Default maximum number of results
    """

    user_id: Identifier(identifier=True, required=True)
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50)
    email: String(required=True)


@domain.projection(limit=None)
class FullReport:
    """Projection with unlimited query results.

    Setting limit=None removes the default 100-record limit.
    """

    report_id: Identifier(identifier=True, required=True)
    title: String(max_length=200, required=True)
    total: Integer(default=0)


@domain.projection(abstract=True)
class BaseView:
    """Abstract projection serving as a base class.

    Abstract projections:
    - Don't require an identifier field
    - Cannot be instantiated
    - Serve as base classes for concrete projections
    """

    age: Integer(default=0)


class ConcreteView(BaseView):
    """Concrete projection inheriting from abstract base.

    Must add its own identifier field.
    """

    view_id: Identifier(identifier=True)
    name: String(max_length=100)


# Register concrete view (abstract is already registered via decorator)
domain.register(ConcreteView)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # UserDirectory with custom options
        user = UserDirectory(
            user_id="USR-001",
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
        )
        domain.repository_for(UserDirectory).add(user)

        print(f"Schema: {UserDirectory.meta_.schema_name}")
        print(f"Order by: {UserDirectory.meta_.order_by}")
        print(f"Limit: {UserDirectory.meta_.limit}")
        assert UserDirectory.meta_.schema_name == "user_directory_view"
        assert UserDirectory.meta_.order_by == ("last_name",)
        assert UserDirectory.meta_.limit == 50

        # FullReport with unlimited results
        print(f"FullReport limit: {FullReport.meta_.limit}")
        assert FullReport.meta_.limit is None

        # BaseView is abstract
        print(f"BaseView abstract: {BaseView.meta_.abstract}")
        assert BaseView.meta_.abstract is True

        print("Projection options working correctly!")
