"""Tests for the canonical golden-path domain in ``examples/reference_app``.

The module lives outside the package tree (under ``examples/``), so it is
loaded by file path with ``spec_from_file_location``, the same pattern
``tests/test_tutorial.py`` uses for the hyphenated ``getting-started`` path.

Each test builds its own domain, so the class carries
``@pytest.mark.no_test_domain`` to opt out of the shared ``test_domain``
autouse fixture.
"""

import importlib.util
import os
import types

import pytest

_MODULE_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "examples",
        "reference_app",
        "blog.py",
    )
)


def _load_module() -> types.ModuleType:
    """Load the ``blog`` module fresh from its file path.

    Loading is not registered in ``sys.modules`` so each call returns an
    independent module with its own ``Domain`` instance. Importing only
    defines the domain; it does not call ``domain.init()`` or run the demo.
    """
    spec = importlib.util.spec_from_file_location("reference_app_blog", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.no_test_domain
class TestReferenceAppQuickstart:
    @pytest.fixture()
    def blog(self):
        """A configured, initialized domain with projection artifacts ready."""
        mod = _load_module()
        domain = mod.domain
        domain.config["command_processing"] = "sync"
        domain.config["event_processing"] = "sync"
        domain.init()
        domain.setup_database()

        yield mod

        domain.drop_database()
        domain.close()

    def test_command_persists_the_published_aggregate(self, blog):
        """PublishPost through domain.process() persists a PUBLISHED post."""
        domain = blog.domain
        with domain.domain_context():
            post_id = domain.process(
                blog.PublishPost(title="Hello, Protean!", body="My first post.")
            )

            post = domain.repository_for(blog.Post).get(post_id)
            assert post is not None
            assert post.title == "Hello, Protean!"
            assert post.status == "PUBLISHED"

    def test_event_handler_ran(self, blog, capsys):
        """The event handler's printed side effect names the published post."""
        domain = blog.domain
        with domain.domain_context():
            domain.process(
                blog.PublishPost(title="Hello, Protean!", body="My first post.")
            )

        out = capsys.readouterr().out
        assert "Event handled: post published (Hello, Protean!)" in out

    def test_projection_query_returns_the_published_post(self, blog):
        """The projector fills the feed with exactly the one published post."""
        domain = blog.domain
        with domain.domain_context():
            post_id = domain.process(
                blog.PublishPost(title="Hello, Protean!", body="My first post.")
            )

            feed = domain.view_for(blog.PublishedPostsFeed).query.all()
            assert feed.total == 1
            row = feed.items[0]
            assert row.post_id == post_id
            assert row.title == "Hello, Protean!"

    def test_import_does_not_initialize_or_run_demo(self, capsys):
        """Importing the module defines the domain without init or the demo.

        The demo (under ``if __name__ == "__main__"``) prints the arc and
        calls ``domain.init()``. Right after import, the providers registry
        is still empty and nothing was printed.
        """
        mod = _load_module()

        captured = capsys.readouterr()
        assert captured.out == ""
        assert len(mod.domain.providers) == 0
