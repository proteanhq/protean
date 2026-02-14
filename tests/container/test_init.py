from protean.utils.container import BaseContainer, OptionsMixin


class TestControlledFinalization:
    def test_that_objects_are_initialized_by_default(self):
        # FIXME Remove OptionsMixin when it becomes optional
        class Foo(BaseContainer, OptionsMixin):
            foo: str | None = None

        foo = Foo()
        assert foo._initialized is True

    def test_that_objects_can_be_initialized_manually(self):
        class Foo(BaseContainer, OptionsMixin):
            foo: str | None = None

            def __init__(self, *args, **kwargs):
                super().__init__(*args, finalize=False, **kwargs)

        foo = Foo()

        assert foo._initialized is False
