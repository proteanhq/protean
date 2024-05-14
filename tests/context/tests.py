import mock
import pytest

from protean.globals import current_domain, g


class TestDomainContext:
    @pytest.fixture
    def test_domain_context(self, test_domain):
        with test_domain.domain_context() as context:
            yield context

    def test_domain_context_provides_domain_app(self, test_domain):
        with test_domain.domain_context():
            assert current_domain._get_current_object() == test_domain

    def test_domain_tearing_down(self, test_domain):
        cleanup_stuff = []

        @test_domain.teardown_domain_context
        def cleanup(exception):
            cleanup_stuff.append(exception)

        with test_domain.domain_context():
            pass

        assert cleanup_stuff == [None]

    def test_domain_tearing_down_with_previous_exception(self, test_domain):
        cleanup_stuff = []

        @test_domain.teardown_domain_context
        def cleanup(exception):
            cleanup_stuff.append(exception)

        try:
            raise Exception("dummy")
        except Exception:
            pass

        with test_domain.domain_context():
            pass

        assert cleanup_stuff == [None]

    def test_domain_tearing_down_with_handled_exception_by_except_block(
        self, test_domain
    ):
        cleanup_stuff = []

        @test_domain.teardown_domain_context
        def cleanup(exception):
            cleanup_stuff.append(exception)

        with test_domain.domain_context():
            try:
                raise Exception("dummy")
            except Exception:
                pass

        assert cleanup_stuff == [None]

    @pytest.mark.skip  # FIXME Could provide a domain level handler to catch and act on exceptions
    def test_domain_tearing_down_with_handled_exception_by_domain_handler(
        self, test_domain
    ):
        # app.config["PROPAGATE_EXCEPTIONS"] = True
        # cleanup_stuff = []

        # @test_domain.teardown_domain_context
        # def cleanup(exception):
        #     cleanup_stuff.append(exception)

        # @test_domain.errorhandler(Exception)
        # def handler(f):
        #     return flask.jsonify(str(f))

        # with domain.domain_context():
        #     client.get("/")

        # assert cleanup_stuff == [None]
        pass

    def test_domain_tearing_down_with_unhandled_exception(self, test_domain):
        test_domain.config["PROPAGATE_EXCEPTIONS"] = True
        cleanup_stuff = []

        @test_domain.teardown_domain_context
        def cleanup(exception):
            cleanup_stuff.append(exception)

        with pytest.raises(Exception):
            # Dummy class that is not registered with domain
            class FooBar:
                pass

            from protean.utils import DomainObjects

            with test_domain.domain_context():
                try:
                    test_domain._get_element_by_class(
                        (DomainObjects.AGGREGATE,), FooBar
                    )
                except Exception:
                    raise Exception("ElementNotFound")

        assert len(cleanup_stuff) == 1
        assert isinstance(cleanup_stuff[0], Exception)
        assert str(cleanup_stuff[0]) == "ElementNotFound"

    def test_domain_context_globals_methods(self, test_domain, test_domain_context):
        # get
        assert g.get("foo") is None
        assert g.get("foo", "bar") == "bar"
        # __contains__
        assert "foo" not in g
        g.foo = "bar"
        assert "foo" in g
        # setdefault
        g.setdefault("bar", "the cake is a lie")
        g.setdefault("bar", "hello world")
        assert g.bar == "the cake is a lie"
        # pop
        assert g.pop("bar") == "the cake is a lie"
        with pytest.raises(KeyError):
            g.pop("bar")
        assert g.pop("bar", "more cake") == "more cake"
        # __iter__
        assert list(g) == ["foo"]
        # __repr__
        assert repr(g) == "<protean.g of 'Test'>"

    def test_custom_domain_ctx_globals_class(self, test_domain):
        class CustomGlobals:
            def __init__(self):
                self.spam = "eggs"

        test_domain.domain_context_globals_class = CustomGlobals
        with test_domain.domain_context():
            assert g.spam == "eggs"

    # Test passing kwargs to domain context during activation
    def test_domain_context_kwargs(self, test_domain):
        with test_domain.domain_context(foo="bar"):
            assert g.foo == "bar"

        assert "foo" not in g

    # Test global attributes are not shared between domain contexts
    def test_domain_context_globals_not_shared(self, test_domain):
        with test_domain.domain_context(foo="bar"):
            assert g.foo == "bar"

            with test_domain.domain_context(foo="baz"):
                assert g.foo == "baz"

    def test_domain_context_activation_calls_validate_domain(self, test_domain):
        mock_validate_domain = mock.Mock()
        test_domain._validate_domain = mock_validate_domain
        with test_domain.domain_context():
            mock_validate_domain.assert_called_once()
