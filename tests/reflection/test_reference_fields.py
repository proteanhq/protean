import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import IncorrectUsageError
from protean.fields import Integer, Reference, String
from protean.utils.reflection import reference_fields


class Account(BaseAggregate):
    email = String(max_length=255, required=True)
    password = String(max_length=255, required=True)


class Author(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    account = Reference(Account)


class Post(BaseAggregate):
    title = String(max_length=100, required=True)
    content = String(max_length=500)
    author = Reference(Author)


class PersonWithoutReferences(BaseAggregate):
    name = String(max_length=50, required=True)
    age = Integer()


def test_reference_fields():
    """Test that reference_fields returns only Reference fields"""
    ref_fields = reference_fields(Author)

    assert len(ref_fields) == 1
    assert "account" in ref_fields
    assert isinstance(ref_fields["account"], Reference)


def test_reference_fields_multiple_references():
    """Test element with multiple Reference fields"""

    class ArticleWithMultipleRefs(BaseAggregate):
        title = String(max_length=100)
        author = Reference(Author)
        reviewer = Reference(Author)

    ref_fields = reference_fields(ArticleWithMultipleRefs)

    assert len(ref_fields) == 2
    assert "author" in ref_fields
    assert "reviewer" in ref_fields
    assert all(isinstance(field, Reference) for field in ref_fields.values())


def test_reference_fields_on_element_without_references():
    """Test element with no Reference fields returns empty dict"""
    ref_fields = reference_fields(PersonWithoutReferences)

    assert len(ref_fields) == 0
    assert ref_fields == {}


def test_reference_fields_on_instance():
    """Test reference_fields works with instances"""
    author = Author(first_name="John", last_name="Doe")
    ref_fields = reference_fields(author)

    assert len(ref_fields) == 1
    assert "account" in ref_fields
    assert isinstance(ref_fields["account"], Reference)


def test_reference_fields_excludes_non_reference_fields():
    """Test that reference_fields excludes regular fields and other types"""
    ref_fields = reference_fields(Post)

    # Should only include the Reference field, not String fields
    assert len(ref_fields) == 1
    assert "author" in ref_fields
    assert "title" not in ref_fields
    assert "content" not in ref_fields
    assert isinstance(ref_fields["author"], Reference)


def test_reference_fields_on_non_element():
    """Test reference_fields raises error on non-element class"""

    class Dummy:
        pass

    with pytest.raises(IncorrectUsageError) as exception:
        reference_fields(Dummy)

    assert exception.value.args[0] == (
        "<class 'test_reference_fields.test_reference_fields_on_non_element.<locals>.Dummy'> "
        "does not have fields"
    )


def test_reference_fields_with_string_reference():
    """Test Reference field defined with string class name"""

    class BookWithStringRef(BaseAggregate):
        title = String(max_length=100)
        author = Reference("Author")

    ref_fields = reference_fields(BookWithStringRef)

    assert len(ref_fields) == 1
    assert "author" in ref_fields
    assert isinstance(ref_fields["author"], Reference)
