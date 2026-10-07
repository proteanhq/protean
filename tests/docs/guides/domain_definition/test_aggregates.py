"""The examples on the aggregates guide behave as the page says."""

import uuid
from datetime import date

import pytest

from protean.exceptions import NotSupportedError, ValidationError
from protean.utils.reflection import declared_fields, fields
from tests.docs.support import load_example


def test_post_gets_an_identity_and_keeps_its_values():
    example = load_example("guides/domain-definition/001.py")
    example.publishing.init(traverse=False)

    with example.publishing.domain_context():
        post = example.Post(name="My First Post", created_on="2024-01-01")

    assert uuid.UUID(post.id)
    assert post.name == "My First Post"
    assert post.created_on == date(2024, 1, 1)


def test_post_rejects_a_name_over_its_max_length():
    example = load_example("guides/domain-definition/001.py")
    example.publishing.init(traverse=False)

    with example.publishing.domain_context(), pytest.raises(ValidationError) as exc:
        example.Post(name="x" * 51)

    assert "name" in exc.value.messages


def test_post_serializes_to_a_dict_with_its_fields(capsys):
    load_example("guides/domain-definition/002.py")

    printed = capsys.readouterr().out
    assert '"name": "My First Post"' in printed
    assert '"created_on": "2024-01-01"' in printed


def test_user_inherits_the_timestamp_fields():
    example = load_example("guides/domain-definition/003.py")

    assert list(declared_fields(example.User)) == [
        "created_at",
        "updated_at",
        "name",
        "timezone",
        "id",
    ]
    assert example.TimeStamped.meta_.abstract is True


def test_abstract_timestamped_cannot_be_instantiated():
    example = load_example("guides/domain-definition/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        with pytest.raises(NotSupportedError):
            example.TimeStamped()
        user = example.User(name="Jane")

    assert user.created_at is not None


def test_user_is_persisted_in_the_archive_provider(tmp_path, monkeypatch):
    # The example's SQLite URIs are relative, so init creates the files in cwd.
    monkeypatch.chdir(tmp_path)
    example = load_example("guides/domain-definition/004.py")
    example.domain.init(traverse=False)

    assert example.User.meta_.provider == "archive"
    assert set(example.domain.providers) == {"default", "archive"}


def test_event_sourced_order_is_placed_through_its_apply_handler():
    example = load_example("guides/domain-definition/aggregates/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order.place("Jane")

    assert example.Order.meta_.is_event_sourced is True
    assert order.customer_name == "Jane"
    assert order.status == "PENDING"
    assert len(order._events) == 1
    assert order._events[0].order_id == str(order.id)


def test_order_uses_the_custom_stream_category():
    example = load_example("guides/domain-definition/aggregates/002.py")

    assert example.Order.meta_.stream_category == "ordering::customer_orders"


def test_customer_emits_fact_events():
    example = load_example("guides/domain-definition/aggregates/003.py")
    example.domain.init(traverse=False)

    assert example.Customer.meta_.fact_events is True
    assert "name" in fields(example.Customer)


def test_aggregates_carry_their_query_limits():
    example = load_example("guides/domain-definition/aggregates/004.py")

    assert example.Product.meta_.limit == 500
    assert example.AuditLog.meta_.limit is None


def test_order_declares_a_unique_and_a_partial_index():
    example = load_example("guides/domain-definition/aggregates/005.py")
    example.domain.init(traverse=False)

    indexes = example.Order.meta_.indexes
    assert len(indexes) == 2
    unique, partial = indexes
    assert unique.fields == ("email",)
    assert unique.unique is True
    assert partial.name == "ix_active"
    assert partial.fields == ("status", "priority")
    assert partial.desc == ("priority",)
    assert partial.where.children == [("status__in", ["pending", "failed"])]


def test_invoice_total_defaults_from_subtotal_and_tax_rate():
    example = load_example("guides/domain-definition/aggregates/006.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        derived = example.Invoice(subtotal=100.0)
        given = example.Invoice(subtotal=100.0, total=50.0)

    assert derived.total == pytest.approx(110.0)
    assert given.total == 50.0


def test_post_with_stats_and_comments_links_both_children():
    example = load_example("guides/domain-definition/008.py")
    example.publishing.init(traverse=False)

    with example.publishing.domain_context():
        post = example.Post(title="Hello")
        post.stats = example.Statistic(likes=3, dislikes=0)
        post.add_comments(example.Comment(content="Nice"))

    assert post.created_at is not None
    assert post.stats.post_id == post.id
    assert post.stats.likes == 3
    assert len(post.comments) == 1
    assert post.comments[0].post_id == post.id


def test_post_title_rejects_a_value_over_its_max_length():
    example = load_example("guides/domain-definition/008.py")
    example.publishing.init(traverse=False)

    with example.publishing.domain_context(), pytest.raises(ValidationError) as exc:
        example.Post(title="x" * 51)

    assert "title" in exc.value.messages


def test_saved_post_lists_its_comments_in_to_dict():
    example = load_example("guides/domain-definition/008.py")
    example.publishing.init(traverse=False)

    with example.publishing.domain_context():
        post = example.Post(title="Foo")
        post.add_comments(
            [example.Comment(content="bar"), example.Comment(content="baz")]
        )
        example.publishing.repository_for(example.Post).add(post)

    data = post.to_dict()
    assert list(data) == ["title", "created_at", "id", "stats", "comments", "_version"]
    assert data["stats"] is None
    assert data["_version"] == 0
    assert [list(c) for c in data["comments"]] == [["content", "added_at", "id"]] * 2
    assert [c["content"] for c in data["comments"]] == ["bar", "baz"]
