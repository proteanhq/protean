from protean.core.queryset import Q


class TestQ:
    """Class that holds tests for Q Objects"""

    def test_deconstruct(self):
        q = Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert path == "protean.utils.query.Q"
        assert args == ()
        assert kwargs == {"price__gt": 10.0}

    def test_deconstruct_negated(self):
        q = ~Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert args == ()
        assert kwargs == {
            "price__gt": 10.0,
            "_negated": True,
        }

    def test_deconstruct_or(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q3 = q1 | q2
        path, args, kwargs = q3.deconstruct()
        assert args == (("price__gt", 10.0), ("price", 11.0),)
        assert kwargs == {"_connector": "OR"}

    def test_deconstruct_and(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q = q1 & q2
        path, args, kwargs = q.deconstruct()
        assert args == (("price__gt", 10.0), ("price", 11.0),)
        assert kwargs == {}

    def test_deconstruct_multiple_kwargs(self):
        q = Q(price__gt=10.0, price=11.0)
        path, args, kwargs = q.deconstruct()
        assert args == (("price", 11.0), ("price__gt", 10.0),)
        assert kwargs == {}

    def test_reconstruct(self):
        q = Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q

    def test_reconstruct_negated(self):
        q = ~Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q

    def test_reconstruct_or(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q = q1 | q2
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q

    def test_reconstruct_and(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q = q1 & q2
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q
