import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import ConfigurationError
from protean.fields import HasOne, Reference, String
from protean.reflection import attributes, declared_fields


class Book(BaseAggregate):
    title = String(required=True, max_length=100)
    author = HasOne("Author")


class Author(BaseEntity):
    name = String(required=True, max_length=50)
    book = Reference("Book")


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(Book)
    test_domain.register(Author, part_of=Book)
    test_domain.init(traverse=False)


class TestHasOneFieldsInProperties:
    def test_that_has_one_field_appears_in_fields(self):
        assert "author" in declared_fields(Book)

    def test_that_has_one_field_does_not_appear_in_attributes(self):
        assert "author" not in attributes(Book)

    def test_that_reference_field_appears_in_fields(self):
        assert "book" in declared_fields(Author)

    def test_that_reference_field_does_not_appear_in_attributes(self):
        assert "book" not in attributes(Author)


class TestHasOneField:
    def test_that_has_one_field_cannot_be_linked_to_aggregates(self, test_domain):
        class InvalidAggregate(BaseAggregate):
            author = HasOne("Book")

        test_domain.register(InvalidAggregate)
        with pytest.raises(ConfigurationError) as exc:
            # The `author` HasOne field is invalid because it is linked to an Aggregate
            test_domain._validate_domain()

        assert exc.value.args[0]["element"] == "Unresolved references in domain Test"
        assert "Book" in exc.value.args[0]["unresolved"]


class TestHasOnePersistence:
    def test_that_has_one_field_is_persisted_along_with_aggregate(self, test_domain):
        author = Author(name="John Doe")
        book = Book(title="My Book", author=author)

        test_domain.repository_for(Book).add(book)

        assert book.id is not None
        assert book.author.id is not None

        persisted_book = test_domain.repository_for(Book).get(book.id)
        assert persisted_book.author == author
        assert persisted_book.author.id == author.id
        assert persisted_book.author.name == author.name

    def test_that_has_one_field_is_persisted_on_aggregate_update(self, test_domain):
        book = Book(title="My Book")
        test_domain.repository_for(Book).add(book)

        assert book.id is not None
        assert book.author is None

        author = Author(name="John Doe")

        # Fetch the persisted book and update its author
        persisted_book = test_domain.repository_for(Book).get(book.id)
        persisted_book.author = author
        test_domain.repository_for(Book).add(persisted_book)

        # Fetch it again to ensure the author is persisted
        persisted_book = test_domain.repository_for(Book).get(book.id)

        # Ensure that the author is persisted along with the book
        assert persisted_book.author == author
        assert persisted_book.author.id == author.id
        assert persisted_book.author.name == author.name

    def test_that_has_one_field_is_updated_with_new_entity_on_aggregate_update(
        self, test_domain
    ):
        author = Author(name="John Doe")
        book = Book(title="My Book", author=author)

        test_domain.repository_for(Book).add(book)

        persisted_book = test_domain.repository_for(Book).get(book.id)

        # Switch the author to a new one
        new_author = Author(name="Jane Doe")
        persisted_book.author = new_author

        test_domain.repository_for(Book).add(persisted_book)

        # Fetch the book again to ensure the author is updated
        updated_book = test_domain.repository_for(Book).get(persisted_book.id)
        assert updated_book.author == new_author
        assert updated_book.author.id == new_author.id
        assert updated_book.author.name == new_author.name

    def test_that_has_one_field_can_be_removed_on_aggregate_update(self, test_domain):
        author = Author(name="John Doe")
        book = Book(title="My Book", author=author)

        test_domain.repository_for(Book).add(book)

        persisted_book = test_domain.repository_for(Book).get(book.id)

        # Remove the author from the book
        persisted_book.author = None

        test_domain.repository_for(Book).add(persisted_book)

        # Fetch the book again to ensure the author is removed
        updated_book = test_domain.repository_for(Book).get(persisted_book.id)
        assert updated_book.author is None
