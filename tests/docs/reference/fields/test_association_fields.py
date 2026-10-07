"""The examples on the association fields reference behave as the page says."""

import pytest

from protean.exceptions import ObjectNotFoundError, TooManyObjectsError
from protean.utils.reflection import attributes, declared_fields
from tests.docs.support import load_example


def test_has_one_author_is_linked_to_its_book_and_persisted_with_it():
    example = load_example("guides/domain-definition/fields/association-fields/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        book = example.Book(
            title="The Great Gatsby",
            author=example.Author(name="F. Scott Fitzgerald"),
        )
        repo = example.domain.repository_for(example.Book)
        repo.add(book)
        stored = repo.get(book.id)

    assert book.author.book_id == book.id
    assert stored.author.name == "F. Scott Fitzgerald"
    assert stored.author.book_id == book.id


def test_has_one_adds_a_book_reference_and_a_book_id_shadow_field():
    example = load_example("guides/domain-definition/fields/association-fields/001.py")
    example.domain.init(traverse=False)

    assert list(declared_fields(example.Author)) == ["name", "id", "book"]
    assert list(attributes(example.Author)) == ["name", "id", "book_id"]


def test_has_many_add_comments_links_each_comment_to_the_post():
    example = load_example("guides/domain-definition/fields/association-fields/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        post = example.Post(
            title="Foo",
            comments=[example.Comment(content="Bar"), example.Comment(content="Baz")],
        )
        post.add_comments(example.Comment(content="Qux"))

    assert [comment.content for comment in post.comments] == ["Bar", "Baz", "Qux"]
    assert all(comment.post_id == post.id for comment in post.comments)


def test_has_many_remove_comments_drops_the_comment():
    example = load_example("guides/domain-definition/fields/association-fields/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        bar = example.Comment(content="Bar")
        post = example.Post(title="Foo", comments=[bar, example.Comment(content="Baz")])
        post.remove_comments(bar)

    assert [comment.content for comment in post.comments] == ["Baz"]


def test_filter_and_get_one_from_comments_find_matching_comments():
    example = load_example("guides/domain-definition/fields/association-fields/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        post = example.Post(
            title="Foo",
            comments=[
                example.Comment(content="Bar", rating=2.5),
                example.Comment(content="Baz", rating=5),
                example.Comment(content="Baz", rating=4),
            ],
        )
        matches = post.filter_comments(content="Bar", rating=2.5)
        one = post.get_one_from_comments(content="Bar")
        with pytest.raises(ObjectNotFoundError):
            post.get_one_from_comments(content="Missing")
        with pytest.raises(TooManyObjectsError):
            post.get_one_from_comments(content="Baz")

    assert len(matches) == 1
    assert matches[0].to_dict() == {
        "content": "Bar",
        "rating": 2.5,
        "id": matches[0].id,
    }
    assert one.id == matches[0].id
    assert post.filter_comments(content="Missing") == []


def test_explicit_reference_holds_the_post_id():
    example = load_example("guides/domain-definition/fields/association-fields/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        post = example.Post(title="Foo")
        post.add_comments(example.Comment(content="Bar"))

    assert list(attributes(example.Comment)) == ["content", "id", "post_id"]
    assert len(post.comments) == 1
    assert post.comments[0].post_id == post.id


def test_referenced_as_and_via_store_the_order_id_in_order_number():
    example = load_example("guides/domain-definition/fields/association-fields/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order()
        order.add_items(example.OrderItem(quantity=2))
        repo = example.domain.repository_for(example.Order)
        repo.add(order)
        stored = repo.get(order.id)

    assert list(attributes(example.OrderItem)) == ["quantity", "id", "order_number"]
    assert len(stored.items) == 1
    assert stored.items[0].quantity == 2
    assert stored.items[0].order_number == order.id


def test_via_stores_the_product_id_in_product_sku():
    example = load_example("guides/domain-definition/fields/association-fields/005.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        product = example.Product(name="Lamp")
        product.add_reviews(example.Review(content="Bright"))
        repo = example.domain.repository_for(example.Product)
        repo.add(product)
        stored = repo.get(product.id)

    assert len(stored.reviews) == 1
    assert stored.reviews[0].content == "Bright"
    assert stored.reviews[0].product_sku == product.id
