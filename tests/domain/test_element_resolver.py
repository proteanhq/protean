"""Tests for ElementResolver -- the extracted reference resolution logic.

These tests exercise the resolver methods through the Domain's ``init()``
pipeline (the same way they run in production) to verify that the extracted
``ElementResolver`` class resolves string references, assigns aggregate
clusters, and propagates aggregate-level options correctly.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.fields import (
    HasMany,
    HasOne,
    Identifier,
    Integer,
    Reference,
    String,
    ValueObject,
)
from protean.utils.reflection import declared_fields


# ============================================================================
# Shared domain element fixtures
# ============================================================================


class Post(BaseAggregate):
    title: String(max_length=100)


class Comment(BaseEntity):
    body: String(max_length=500)


class Tag(BaseEntity):
    label: String(max_length=50)


class PostPublished(BaseEvent):
    post_id: Identifier()


class PublishPost(BaseCommand):
    post_id: Identifier()


class Email(BaseValueObject):
    address: String(max_length=255)


# ============================================================================
# resolve_references -- Association (HasMany)
# ============================================================================


class TestResolveHasManyStringReference:
    """HasMany('Comment') string reference resolves to the Comment class."""

    def test_has_many_string_resolves_to_entity_class(self, test_domain):
        class Blog(BaseAggregate):
            title: String(max_length=100)
            comments = HasMany("Comment")

        test_domain.register(Blog)
        test_domain.register(Comment, part_of=Blog)
        test_domain.init(traverse=False)

        assert declared_fields(Blog)["comments"].to_cls is Comment

    def test_has_many_pending_resolutions_cleared_after_init(self, test_domain):
        class Blog(BaseAggregate):
            title: String(max_length=100)
            comments = HasMany("Comment")

        test_domain.register(Blog)
        test_domain.register(Comment, part_of=Blog)
        test_domain.init(traverse=False)

        assert "Comment" not in test_domain._pending_class_resolutions


# ============================================================================
# resolve_references -- Association (HasOne)
# ============================================================================


class TestResolveHasOneStringReference:
    """HasOne('Tag') string reference resolves to the Tag class."""

    def test_has_one_string_resolves_to_entity_class(self, test_domain):
        class Article(BaseAggregate):
            title: String(max_length=100)
            featured_tag = HasOne("Tag")

        test_domain.register(Article)
        test_domain.register(Tag, part_of=Article)
        test_domain.init(traverse=False)

        assert declared_fields(Article)["featured_tag"].to_cls is Tag


# ============================================================================
# resolve_references -- Association (Reference)
# ============================================================================


class TestResolveReferenceStringReference:
    """Reference('Post') string reference resolves to the Post class."""

    def test_reference_string_resolves_to_aggregate_class(self, test_domain):
        class Bookmark(BaseEntity):
            note: String(max_length=200)
            post = Reference("Post")

        test_domain.register(Post)
        test_domain.register(Bookmark, part_of=Post)
        test_domain.init(traverse=False)

        assert declared_fields(Bookmark)["post"].to_cls is Post


# ============================================================================
# resolve_references -- ValueObject string reference
# ============================================================================


class TestResolveValueObjectStringReference:
    """ValueObject('Email') string reference resolves to the Email class."""

    def test_value_object_string_resolves_to_vo_class(self, test_domain):
        class Author(BaseAggregate):
            name: String(max_length=100)
            email = ValueObject("Email")

        test_domain.register(Author)
        test_domain.register(Email)
        test_domain.init(traverse=False)

        assert declared_fields(Author)["email"].value_object_cls is Email

    def test_value_object_pending_resolutions_cleared(self, test_domain):
        class Author(BaseAggregate):
            name: String(max_length=100)
            email = ValueObject("Email")

        test_domain.register(Author)
        test_domain.register(Email)
        test_domain.init(traverse=False)

        assert "Email" not in test_domain._pending_class_resolutions


# ============================================================================
# resolve_references -- AggregateCls (part_of as string)
# ============================================================================


class TestResolveAggregateClsStringReference:
    """Entity with part_of='Post' (string) resolves to the Post class."""

    def test_entity_part_of_string_resolves_to_aggregate(self, test_domain):
        class Reaction(BaseEntity):
            emoji: String(max_length=10)

        test_domain.register(Post)
        test_domain.register(Reaction, part_of="Post")
        test_domain.init(traverse=False)

        assert Reaction.meta_.part_of is Post

    def test_event_part_of_string_resolves_to_aggregate(self, test_domain):
        class PostArchived(BaseEvent):
            post_id: Identifier()

        test_domain.register(Post)
        test_domain.register(PostArchived, part_of="Post")
        test_domain.init(traverse=False)

        assert PostArchived.meta_.part_of is Post

    def test_command_part_of_string_resolves_to_aggregate(self, test_domain):
        class ArchivePost(BaseCommand):
            post_id: Identifier()

        test_domain.register(Post)
        test_domain.register(ArchivePost, part_of="Post")
        test_domain.init(traverse=False)

        assert ArchivePost.meta_.part_of is Post


# ============================================================================
# resolve_references -- Unresolved references are left pending
# ============================================================================


class TestUnresolvedReferencesRemainPending:
    """When a target is not registered, the reference stays in _pending_class_resolutions."""

    @pytest.mark.no_test_domain
    def test_unresolved_has_many_stays_pending(self):
        from protean.domain import Domain

        domain = Domain(__name__, "Tests")

        class Catalog(BaseAggregate):
            name: String(max_length=100)
            items = HasMany("CatalogItem")

        domain.register(Catalog)

        # Call resolve_references directly (not init, which would validate)
        domain._resolver.resolve_references()

        assert "CatalogItem" in domain._pending_class_resolutions


# ============================================================================
# assign_aggregate_clusters -- Aggregates
# ============================================================================


class TestAssignAggregateClusterToAggregate:
    """Aggregates are their own aggregate_cluster."""

    def test_aggregate_is_its_own_cluster(self, test_domain):
        test_domain.register(Post)
        test_domain.init(traverse=False)

        assert Post.meta_.aggregate_cluster is Post


# ============================================================================
# assign_aggregate_clusters -- Entities
# ============================================================================


class TestAssignAggregateClusterToEntity:
    """Entities get aggregate_cluster from their part_of chain."""

    def test_direct_child_entity_gets_aggregate_cluster(self, test_domain):
        test_domain.register(Post)
        test_domain.register(Comment, part_of=Post)
        test_domain.init(traverse=False)

        assert Comment.meta_.aggregate_cluster is Post

    def test_nested_entity_gets_root_aggregate_cluster(self, test_domain):
        """An entity nested under another entity still gets the root aggregate."""

        class Order(BaseAggregate):
            ref: String(max_length=50)

        class LineItem(BaseEntity):
            sku: String(max_length=50)

        class Discount(BaseEntity):
            percent: Integer()

        test_domain.register(Order)
        test_domain.register(LineItem, part_of=Order)
        test_domain.register(Discount, part_of=LineItem)
        test_domain.init(traverse=False)

        assert LineItem.meta_.aggregate_cluster is Order
        assert Discount.meta_.aggregate_cluster is Order


# ============================================================================
# assign_aggregate_clusters -- Events and Commands
# ============================================================================


class TestAssignAggregateClusterToEvent:
    """Events get aggregate_cluster from their part_of aggregate."""

    def test_event_gets_aggregate_cluster(self, test_domain):
        test_domain.register(Post)
        test_domain.register(PostPublished, part_of=Post)
        test_domain.init(traverse=False)

        assert PostPublished.meta_.aggregate_cluster is Post


class TestAssignAggregateClusterToCommand:
    """Commands get aggregate_cluster from their part_of aggregate."""

    def test_command_gets_aggregate_cluster(self, test_domain):
        test_domain.register(Post)
        test_domain.register(PublishPost, part_of=Post)
        test_domain.init(traverse=False)

        assert PublishPost.meta_.aggregate_cluster is Post


# ============================================================================
# assign_aggregate_clusters -- Process Managers
# ============================================================================


class TestAssignAggregateClusterToProcessManager:
    """Process managers are their own aggregate_cluster, similar to aggregates."""

    def test_process_manager_is_its_own_cluster(self, test_domain):
        from protean.core.process_manager import BaseProcessManager
        from protean.utils.mixins import handle

        class PaymentReceived(BaseEvent):
            order_id: Identifier()

        class FulfillmentPM(BaseProcessManager):
            @handle(PaymentReceived, start=True, correlate="order_id")
            def on_payment(self, event: PaymentReceived) -> None:
                pass

        test_domain.register(Post)
        test_domain.register(PaymentReceived, part_of=Post)
        test_domain.register(FulfillmentPM)
        test_domain.init(traverse=False)

        assert FulfillmentPM.meta_.aggregate_cluster is FulfillmentPM


# ============================================================================
# set_aggregate_cluster_options -- Provider propagation
# ============================================================================


class TestSetAggregateClusterOptions:
    """Provider option is consistent between aggregate and child entities."""

    def test_entity_and_aggregate_share_default_provider(self, test_domain):
        test_domain.register(Post)
        test_domain.register(Comment, part_of=Post)
        test_domain.init(traverse=False)

        assert Post.meta_.provider == "default"
        assert Comment.meta_.provider == "default"

    def test_entity_provider_set_by_propagation_when_missing(self, test_domain):
        """When an entity's meta does not have a provider attribute,
        set_aggregate_cluster_options propagates the aggregate's provider."""

        class Warehouse(BaseAggregate):
            name: String(max_length=100)

        class Shelf(BaseEntity):
            label: String(max_length=50)

        test_domain.register(Warehouse)
        test_domain.register(Shelf, part_of=Warehouse)

        # Manually remove the provider attribute to simulate the scenario
        # where an entity's meta lacks a provider before propagation runs
        if hasattr(Shelf.meta_, "provider"):
            delattr(Shelf.meta_, "provider")

        test_domain.init(traverse=False)

        # After init, the resolver should have propagated the aggregate's provider
        assert Shelf.meta_.provider == Warehouse.meta_.provider

    def test_entity_registered_with_matching_provider_passes_validation(
        self, test_domain
    ):
        """Entity explicitly registered with the same provider as its aggregate."""

        class Warehouse(BaseAggregate):
            name: String(max_length=100)

        class Shelf(BaseEntity):
            label: String(max_length=50)

        test_domain.register(Warehouse, provider="custom_db")
        test_domain.register(Shelf, part_of=Warehouse, provider="custom_db")
        test_domain.init(traverse=False)

        assert Warehouse.meta_.provider == "custom_db"
        assert Shelf.meta_.provider == "custom_db"


# ============================================================================
# resolve_references -- Multiple resolutions in a single pass
# ============================================================================


class TestMultipleResolutionsInSinglePass:
    """Multiple string references are resolved in one init() call."""

    def test_multiple_association_types_resolved_together(self, test_domain):
        class Store(BaseAggregate):
            name: String(max_length=100)
            products = HasMany("Product")
            manager = HasOne("Manager")

        class Product(BaseEntity):
            name: String(max_length=100)

        class Manager(BaseEntity):
            name: String(max_length=100)

        test_domain.register(Store)
        test_domain.register(Product, part_of=Store)
        test_domain.register(Manager, part_of=Store)
        test_domain.init(traverse=False)

        assert declared_fields(Store)["products"].to_cls is Product
        assert declared_fields(Store)["manager"].to_cls is Manager
        assert "Product" not in test_domain._pending_class_resolutions
        assert "Manager" not in test_domain._pending_class_resolutions


# ============================================================================
# resolve_references -- Mixed Association + ValueObject resolution
# ============================================================================


class TestMixedResolution:
    """Both association and value object string references are resolved together."""

    def test_association_and_value_object_resolved_together(self, test_domain):
        class Contact(BaseAggregate):
            name: String(max_length=100)
            email = ValueObject("Email")
            notes = HasMany("Note")

        class Note(BaseEntity):
            text: String(max_length=500)

        test_domain.register(Contact)
        test_domain.register(Email)
        test_domain.register(Note, part_of=Contact)
        test_domain.init(traverse=False)

        assert declared_fields(Contact)["email"].value_object_cls is Email
        assert declared_fields(Contact)["notes"].to_cls is Note


# ============================================================================
# Full pipeline -- resolve + cluster + options in sequence
# ============================================================================


class TestFullResolverPipeline:
    """All three resolver steps work correctly when run together via init()."""

    def test_full_pipeline_resolves_and_assigns_cluster(self, test_domain):
        class Company(BaseAggregate):
            name: String(max_length=100)
            employees = HasMany("Employee")

        class Employee(BaseEntity):
            name: String(max_length=100)

        class HireEmployee(BaseCommand):
            employee_name: String(max_length=100)

        class EmployeeHired(BaseEvent):
            employee_name: String(max_length=100)

        test_domain.register(Company)
        test_domain.register(Employee, part_of=Company)
        test_domain.register(HireEmployee, part_of=Company)
        test_domain.register(EmployeeHired, part_of=Company)
        test_domain.init(traverse=False)

        # References resolved
        assert declared_fields(Company)["employees"].to_cls is Employee

        # Aggregate clusters assigned
        assert Company.meta_.aggregate_cluster is Company
        assert Employee.meta_.aggregate_cluster is Company
        assert HireEmployee.meta_.aggregate_cluster is Company
        assert EmployeeHired.meta_.aggregate_cluster is Company

        # Provider is consistent (both default)
        assert Employee.meta_.provider == Company.meta_.provider
