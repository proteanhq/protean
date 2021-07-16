from .aggregate_elements_with_value_objects import File, Resource


class TestAggregatesWithValueObjects:
    def test_that_value_object_can_be_embedded_within_aggregate(self):
        resource = Resource(
            title="Resource 1", associated_file=File(url="/server/1.pdf", type="PDF")
        )

        assert resource is not None

    def test_that_embedded_value_objects_are_unique(self):
        resource1 = Resource(
            title="Resource 1", associated_file=File(url="/server/1.pdf", type="PDF")
        )
        resource2 = Resource(
            title="Resource 2", associated_file=File(url="/server/2.pdf", type="PDF")
        )

        assert resource1.associated_file is not None
        assert resource2.associated_file is not None
        assert resource1.associated_file != resource2.associated_file
        assert resource1.associated_file.url == "/server/1.pdf"
        assert resource1.associated_file_url == "/server/1.pdf"
        assert resource2.associated_file.url == "/server/2.pdf"
        assert resource2.associated_file_url == "/server/2.pdf"

    def test_that_attributes_from_embedded_objects_are_attached(self):
        resource1 = Resource(
            title="Resource 1", associated_file=File(url="/server/1.pdf", type="PDF")
        )
        assert all(
            key in resource1.__dict__
            for key in [
                "title",
                "associated_file",
                "associated_file_url",
                "associated_file_type",
            ]
        )

        resource2 = Resource(title="Resource 2")
        assert all(
            key in resource2.__dict__
            for key in ["title", "associated_file_url", "associated_file_type"]
        )
