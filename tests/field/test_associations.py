from .elements import Comment, Post


class TestReferenceField:
    def test_that_reference_field_has_a_shadow_attribute(self):
        assert "post_id" in Comment.meta_.attributes

    def test_that_reference_field_does_not_appear_among_fields(self):
        assert "post_id" not in Comment.meta_.declared_fields


class TestHasOneField:
    def test_that_has_one_field_appears_in_fields(self):
        assert "meta" in Post.meta_.declared_fields

    def test_that_has_one_field_does_not_appear_in_attributes(self):
        assert "meta" not in Post.meta_.attributes


class TestHasManyField:
    def test_that_has_many_field_appears_in_fields(self):
        assert "comments" in Post.meta_.declared_fields

    def test_that_has_many_field_does_not_appear_in_attributes(self):
        assert "comments" not in Post.meta_.attributes
