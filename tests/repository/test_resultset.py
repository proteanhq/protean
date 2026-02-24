from protean.core.queryset import ResultSet


class TestResultSet:
    def test_successful_resultset_initialization(self):
        resultset = ResultSet(offset=0, limit=10, total=2, items=["foo", "bar"])

        assert resultset is not None

    def test_resultset_properties(self):
        resultset = ResultSet(offset=0, limit=10, total=2, items=["foo", "bar"])

        assert len(resultset) == 2
        assert resultset.first == "foo"
        assert [item for item in resultset] == ["foo", "bar"]  # Test __iter__

    def test_resultset_first_and_last(self):
        resultset = ResultSet(
            offset=0, limit=10, total=2, items=["foo", "bar", "baz", "qux"]
        )

        assert resultset.first == "foo"
        assert resultset.last == "qux"

    def test_pagination_properties_of_resultset(self):
        resultset = ResultSet(offset=0, limit=10, total=2, items=["foo", "bar"])
        has_next_resultset = ResultSet(offset=0, limit=2, total=4, items=["foo", "bar"])
        has_prev_resultset = ResultSet(offset=2, limit=2, total=4, items=["foo", "bar"])

        assert resultset.has_prev is False
        assert resultset.has_next is False
        assert has_next_resultset.has_next is True
        assert has_next_resultset.has_prev is False
        assert has_prev_resultset.has_next is False
        assert has_prev_resultset.has_prev is True

    def test_boolean_evaluation_of_resultset(self):
        resultset = ResultSet(offset=0, limit=10, total=2, items=["foo", "bar"])
        empty_resultset = ResultSet(offset=0, limit=10, total=0, items=[])

        assert bool(resultset) is True
        assert bool(empty_resultset) is False

    def test_resultset_repr(self):
        resultset = ResultSet(offset=0, limit=10, total=2, items=["foo", "bar"])

        assert repr(resultset) == "<ResultSet: 2 items>"

    def test_resultset_to_dict(self):
        resultset = ResultSet(offset=0, limit=10, total=2, items=["foo", "bar"])
        assert resultset.to_dict() == {
            "offset": 0,
            "limit": 10,
            "total": 2,
            "page": 1,
            "page_size": 10,
            "total_pages": 1,
            "has_next": False,
            "has_prev": False,
            "items": ["foo", "bar"],
        }


class TestPageProperty:
    """Tests for ResultSet.page — current page number (1-indexed)."""

    def test_page_first_page(self):
        rs = ResultSet(offset=0, limit=10, total=50, items=["a"])
        assert rs.page == 1

    def test_page_second_page(self):
        rs = ResultSet(offset=10, limit=10, total=50, items=["a"])
        assert rs.page == 2

    def test_page_third_page(self):
        rs = ResultSet(offset=20, limit=10, total=50, items=["a"])
        assert rs.page == 3

    def test_page_last_page(self):
        rs = ResultSet(offset=90, limit=10, total=100, items=["a"])
        assert rs.page == 10

    def test_page_mid_page_offset(self):
        """Offset within the first page boundary still returns page 1."""
        rs = ResultSet(offset=5, limit=10, total=50, items=["a"])
        assert rs.page == 1

    def test_page_with_unlimited_limit(self):
        rs = ResultSet(offset=0, limit=None, total=50, items=["a"])
        assert rs.page == 1

    def test_page_with_offset_and_unlimited_limit(self):
        rs = ResultSet(offset=5, limit=None, total=50, items=["a"])
        assert rs.page == 1

    def test_page_empty_results(self):
        rs = ResultSet(offset=0, limit=10, total=0, items=[])
        assert rs.page == 1


class TestPageSizeProperty:
    """Tests for ResultSet.page_size — alias for limit."""

    def test_page_size_returns_limit(self):
        rs = ResultSet(offset=0, limit=10, total=20, items=["a"])
        assert rs.page_size == 10

    def test_page_size_returns_none_when_unlimited(self):
        rs = ResultSet(offset=0, limit=None, total=20, items=["a"])
        assert rs.page_size is None

    def test_page_size_with_large_limit(self):
        rs = ResultSet(offset=0, limit=1000, total=50, items=["a"])
        assert rs.page_size == 1000


class TestTotalPagesProperty:
    """Tests for ResultSet.total_pages — total number of pages."""

    def test_total_pages_exact_division(self):
        rs = ResultSet(offset=0, limit=10, total=30, items=["a"])
        assert rs.total_pages == 3

    def test_total_pages_with_remainder(self):
        rs = ResultSet(offset=0, limit=10, total=25, items=["a"])
        assert rs.total_pages == 3

    def test_total_pages_single_page(self):
        rs = ResultSet(offset=0, limit=10, total=5, items=["a"])
        assert rs.total_pages == 1

    def test_total_pages_empty_results(self):
        rs = ResultSet(offset=0, limit=10, total=0, items=[])
        assert rs.total_pages == 0

    def test_total_pages_unlimited(self):
        rs = ResultSet(offset=0, limit=None, total=50, items=["a"])
        assert rs.total_pages == 1

    def test_total_pages_unlimited_empty(self):
        rs = ResultSet(offset=0, limit=None, total=0, items=[])
        assert rs.total_pages == 0

    def test_total_pages_exact_boundary(self):
        rs = ResultSet(offset=0, limit=10, total=10, items=["a"])
        assert rs.total_pages == 1

    def test_total_pages_one_over_boundary(self):
        rs = ResultSet(offset=0, limit=10, total=11, items=["a"])
        assert rs.total_pages == 2

    def test_total_pages_large_dataset(self):
        rs = ResultSet(offset=0, limit=100, total=999, items=["a"])
        assert rs.total_pages == 10


class TestHasNextWithUnlimitedLimit:
    """Tests for the has_next fix when limit is None."""

    def test_has_next_returns_false_when_unlimited(self):
        rs = ResultSet(offset=0, limit=None, total=50, items=["a"])
        assert rs.has_next is False

    def test_has_next_returns_false_when_unlimited_with_offset(self):
        rs = ResultSet(offset=5, limit=None, total=50, items=["a"])
        assert rs.has_next is False


class TestToDictWithPaginationProperties:
    """Tests for to_dict() including page properties."""

    def test_to_dict_includes_page_properties(self):
        rs = ResultSet(offset=10, limit=10, total=25, items=["a"])
        d = rs.to_dict()
        assert d == {
            "offset": 10,
            "limit": 10,
            "total": 25,
            "page": 2,
            "page_size": 10,
            "total_pages": 3,
            "has_next": True,
            "has_prev": True,
            "items": ["a"],
        }

    def test_to_dict_with_unlimited_limit(self):
        rs = ResultSet(offset=0, limit=None, total=50, items=["a", "b"])
        d = rs.to_dict()
        assert d["page"] == 1
        assert d["page_size"] is None
        assert d["total_pages"] == 1
        assert d["has_next"] is False
        assert d["has_prev"] is False


class TestCombinedPaginationProperties:
    """Tests verifying that all pagination properties work together correctly."""

    def test_all_properties_mid_pagination(self):
        rs = ResultSet(offset=20, limit=10, total=55, items=["a"] * 10)
        assert rs.page == 3
        assert rs.page_size == 10
        assert rs.total_pages == 6
        assert rs.has_next is True
        assert rs.has_prev is True

    def test_all_properties_first_page(self):
        rs = ResultSet(offset=0, limit=10, total=55, items=["a"] * 10)
        assert rs.page == 1
        assert rs.page_size == 10
        assert rs.total_pages == 6
        assert rs.has_next is True
        assert rs.has_prev is False

    def test_all_properties_last_page(self):
        rs = ResultSet(offset=50, limit=10, total=55, items=["a"] * 5)
        assert rs.page == 6
        assert rs.page_size == 10
        assert rs.total_pages == 6
        assert rs.has_next is False
        assert rs.has_prev is True

    def test_all_properties_single_item_single_page(self):
        rs = ResultSet(offset=0, limit=10, total=1, items=["only"])
        assert rs.page == 1
        assert rs.page_size == 10
        assert rs.total_pages == 1
        assert rs.has_next is False
        assert rs.has_prev is False
