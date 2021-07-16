from protean.port.dao import ResultSet


class TestResultSet:
    def test_successful_resultset_initialization(self):
        resultset = ResultSet(offset=0, limit=10, total=2, items=["foo", "bar"])

        assert resultset is not None

    def test_resultset_properties(self):
        resultset = ResultSet(offset=0, limit=10, total=2, items=["foo", "bar"])

        assert len(resultset) == 2
        assert resultset.first == "foo"
        assert [item for item in resultset] == ["foo", "bar"]  # Test __iter__

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
