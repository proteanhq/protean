"""The examples on the relationships guide link parents and children as the page says."""

import pytest

from protean.exceptions import ValidationError
from protean.utils.reflection import attributes, declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_setting_a_has_one_child_links_it_to_the_blog():
    example = load_example("guides/domain-definition/relationships/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        blog = example.Blog(title="Notes")
        blog.settings = example.BlogSettings(theme="dark")

    assert blog.settings.theme == "dark"
    assert blog.settings.allow_comments is True
    assert blog.settings.blog_id == blog.id


def test_adding_comments_links_each_to_the_post():
    example = load_example("guides/domain-definition/relationships/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        post = example.Post(title="New Post")
        post.add_comments(example.Comment(content="Hello", author="alice"))

    assert len(post.comments) == 1
    assert post.comments[0].post_id == post.id


def test_helper_methods_filter_and_find_comments_by_author():
    example = load_example("guides/domain-definition/relationships/002.py")

    assert len(example.alice_comments) == 2
    assert {c.content for c in example.alice_comments} == {
        "First comment",
        "Third comment",
    }
    assert example.bob_comment.content == "Second comment"


def test_remove_comments_drops_the_comment_from_the_post():
    example = load_example("guides/domain-definition/relationships/002.py")

    with example.domain.domain_context():
        post = example.Post(title="New Post")
        post.add_comments(
            [
                example.Comment(content="Keep", author="alice"),
                example.Comment(content="Drop", author="bob"),
            ]
        )
        post.remove_comments(post.get_one_from_comments(author="bob"))

    assert [c.content for c in post.comments] == ["Keep"]


def test_comment_navigates_back_to_its_post():
    example = load_example("guides/domain-definition/relationships/002.py")

    assert len(example.comments) == 1
    assert example.comment.content == "Great post!"
    assert example.post.id == example.comment.post_id
    assert example.post_id == example.comment.post_id


def test_customer_embeds_the_billing_address_value_object():
    example = load_example("guides/domain-definition/relationships/009.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        customer = example.Customer(
            name="Jane",
            billing_address=example.Address(
                street="1 Main St", city="Springfield", zip_code="62701"
            ),
        )

    assert customer.billing_address.city == "Springfield"
    assert customer.to_dict()["billing_address"]["zip_code"] == "62701"


def test_explicit_reference_holds_the_post_id():
    example = load_example("guides/domain-definition/relationships/003.py")
    example.domain.init(traverse=False)

    assert "post" in declared_fields(example.Comment)

    with example.domain.domain_context():
        post = example.Post(title="Hello")
        post.add_comments(example.Comment(content="Nice", author="bob"))

    assert post.comments[0].post_id == post.id


def test_via_stores_the_product_sku_in_reviewed_sku():
    example = load_example("guides/domain-definition/relationships/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        product = example.Product(name="Lamp", sku="LAMP-01")
        product.add_reviews(example.Review(content="Bright", rating=5))

    review = product.reviews[0]
    assert review.reviewed_sku == "LAMP-01"
    stored = review.to_dict()
    assert stored["reviewed_sku"] == "LAMP-01"
    assert "product_sku" not in stored


def test_via_keeps_the_default_foreign_key_alongside_it():
    example = load_example("guides/domain-definition/relationships/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        product = example.Product(name="Lamp", sku="LAMP-01")
        product.add_reviews(example.Review(content="Bright", rating=5))
        repo = example.domain.repository_for(example.Product)
        repo.add(product)
        stored = repo.get("LAMP-01")

    assert {"reviewed_sku", "product_sku"} <= set(attributes(example.Review))
    assert len(stored.reviews) == 1
    assert stored.reviews[0].reviewed_sku == "LAMP-01"
    assert stored.reviews[0].product_sku == "LAMP-01"


def test_review_rejects_a_rating_above_five():
    example = load_example("guides/domain-definition/relationships/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.Review(content="Too good", rating=6)

    assert "rating" in exc.value.messages


def test_referenced_as_names_the_shadow_field_order_number():
    example = load_example("guides/domain-definition/relationships/005.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order()
        order.add_items(example.OrderItem(product_name="Pen"))

    item = order.items[0]
    assert item.order_number == order.id
    assert not hasattr(item, "order_id")


def test_assigning_a_dict_builds_the_statistic_entity():
    example = load_example("guides/domain-definition/relationships/006.py")

    assert isinstance(example.post.stats, example.Statistic)
    assert example.post.stats.likes == 10
    assert example.post.stats.dislikes == 1
    assert example.post.stats.post_id == example.post.id


def test_order_invariant_requires_at_least_one_item():
    example = load_example("guides/domain-definition/relationships/007.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(items=[example.OrderItem(product_name="Pen")])
        assert len(order.items) == 1

        with pytest.raises(ValidationError) as exc:
            example.Order()

    assert exc.value.messages["items"] == ["Order must have at least one item"]


def test_order_loads_its_customer_by_identity():
    example = load_example("guides/domain-definition/relationships/008.py")

    assert example.order.customer_id == example.jane.id
    assert example.customer.id == example.jane.id
    assert example.customer.email.address == "jane@example.com"


def test_order_requires_a_customer_id():
    example = load_example("guides/domain-definition/relationships/008.py")

    with example.domain.domain_context(), pytest.raises(ValidationError) as exc:
        example.Order()

    assert "customer_id" in exc.value.messages
