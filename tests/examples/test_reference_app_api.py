"""Tests for the FastAPI reference app in ``examples/reference_app/app``.

The app module lives outside the package tree (under ``examples/``), so it is
loaded by file path with ``spec_from_file_location``, the same pattern
``tests/examples/test_reference_app_quickstart.py`` uses for ``blog.py``.

The app runs on SQLite, so this test is deliberately left unmarked (no adapter
marker) and ``protean test`` collects it in the core leg. The class carries
``@pytest.mark.no_test_domain`` because each test builds its own domain and must
opt out of the shared ``test_domain`` autouse fixture.

``TestClient`` is used as a context manager on purpose: a bare ``TestClient(app)``
skips FastAPI's lifespan events, so ``domain.init()`` and ``domain.setup_database()``
would never run and the SQLite tables would be missing.
"""

import importlib.util
import inspect
import os
import types

import pytest
from fastapi.testclient import TestClient

_APP_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "examples", "reference_app", "app"
    )
)
_API_PATH = os.path.join(_APP_DIR, "api.py")
_BLOG_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "examples", "reference_app", "blog.py"
    )
)


def _pin_config_env(monkeypatch, db_path) -> None:
    """Pin every env var the app's ``domain.toml`` reads.

    The config file resolves its provider and URI from the environment, so a
    developer or CI runner with ``DATABASE_PROVIDER``/``BROKER_PROVIDER`` set
    globally would push these tests onto PostgreSQL or Redis. Pinning them here
    keeps the run on SQLite in a throwaway file plus the inline broker, whatever
    the ambient environment holds.
    """
    monkeypatch.setenv("DATABASE_PROVIDER", "sqlite")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("BROKER_PROVIDER", "inline")
    monkeypatch.delenv("BROKER_URL", raising=False)


def _load_module(name: str, path: str) -> types.ModuleType:
    """Load a module fresh from its file path, unregistered in ``sys.modules``."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, (
        f"Could not build a loadable module spec from {path}"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.no_test_domain
class TestReferenceAppApi:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        """A TestClient whose SQLite DB points at a throwaway file.

        Pinning the config env vars before the lifespan runs makes the app's
        ``domain.toml`` resolve to this temp file, so the run is isolated and
        re-runnable. Entering the ``with`` block runs startup (init +
        setup_database); leaving it runs shutdown.
        """
        db_path = tmp_path / "reference_app.db"
        _pin_config_env(monkeypatch, db_path)

        api = _load_module("reference_app_api", _API_PATH)
        with TestClient(api.app) as client:
            # The lifespan has run: confirm the app is actually on SQLite, not
            # the in-memory default it was built with.
            assert api.domain.config["databases"]["default"]["provider"] == "sqlite"
            assert api.domain.config["brokers"]["default"]["provider"] == "inline"
            yield client

    def test_post_then_get_returns_the_published_post(self, client):
        """POST /posts publishes; GET /posts shows the same post in the feed."""
        response = client.post(
            "/posts",
            json={"title": "Hello, Protean!", "body": "My first published post."},
        )
        assert response.status_code == 201, response.text
        post_id = response.json()["id"]
        assert post_id

        feed = client.get("/posts")
        assert feed.status_code == 200, feed.text
        posts = feed.json()["posts"]
        assert len(posts) == 1
        assert posts[0]["post_id"] == post_id
        assert posts[0]["title"] == "Hello, Protean!"

    def test_two_posts_both_appear_in_the_feed(self, client):
        """Posting twice lands both posts in the feed, not just the first."""
        first = client.post("/posts", json={"title": "First", "body": "one"})
        second = client.post("/posts", json={"title": "Second", "body": "two"})
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        ids = {first.json()["id"], second.json()["id"]}
        assert len(ids) == 2

        feed = client.get("/posts")
        assert feed.status_code == 200, feed.text
        posts = feed.json()["posts"]
        assert len(posts) == 2
        assert {post["post_id"] for post in posts} == ids
        assert {post["title"] for post in posts} == {"First", "Second"}

    def test_empty_title_is_a_400(self, client):
        """A validation failure maps to the 400 shape from the exception handlers.

        This proves ``register_exception_handlers`` is wired: an empty title
        raises ``ValidationError`` when the command is built, and the handler
        turns it into ``{"error": ...}`` with status 400.
        """
        response = client.post("/posts", json={"title": "", "body": "no title"})
        assert response.status_code == 400, response.text
        body = response.json()
        assert "error" in body
        assert "title" in body["error"]

        # The rejected post did not reach the feed.
        feed = client.get("/posts")
        assert feed.json()["posts"] == []

    def test_unknown_field_is_a_400(self, client):
        """An unknown key is rejected as a 400, not swallowed or crashed as a 500.

        Protean commands set ``extra="forbid"``, so building the command from a
        payload with an unexpected key raises ``ValidationError``. The handler
        turns that into a 400, and nothing reaches the feed.
        """
        response = client.post("/posts", json={"title": "Hi", "body": "x", "bogus": 1})
        assert response.status_code == 400, response.text
        assert "error" in response.json()

        feed = client.get("/posts")
        assert feed.json()["posts"] == []

    def test_endpoints_are_sync_functions(self, tmp_path, monkeypatch):
        """The endpoints are plain ``def``, so FastAPI runs them in a threadpool.

        ``domain.process()`` and the projection query both block on I/O. An
        ``async def`` endpoint would run that work on the event loop thread and
        stall every other request while it waits.
        """
        _pin_config_env(monkeypatch, tmp_path / "reference_app.db")

        api = _load_module("reference_app_api", _API_PATH)
        assert not inspect.iscoroutinefunction(api.create_post)
        assert not inspect.iscoroutinefunction(api.list_posts)

    def test_app_config_does_not_leak_into_the_quickstart(self, tmp_path, monkeypatch):
        """With the app on SQLite in this process, a fresh ``blog.py`` still resolves memory.

        This loads ``api.py`` and runs its lifespan, so the app applies its own
        ``domain.toml`` and its domain is on SQLite. Even then, loading the
        quickstart fresh by file path resolves the in-memory default: ``blog.py``
        builds its ``Domain`` with ``root_path`` fixed to its own directory, and
        config resolution never descends into the ``app`` subfolder.
        """
        db_path = tmp_path / "reference_app.db"
        _pin_config_env(monkeypatch, db_path)

        api = _load_module("reference_app_api", _API_PATH)
        with TestClient(api.app):
            # The app has applied its SQLite config in this process.
            assert api.domain.config["databases"]["default"]["provider"] == "sqlite"
            # A fresh quickstart load still resolves the in-memory default.
            blog = _load_module("reference_app_blog", _BLOG_PATH)
            assert blog.domain.config["databases"]["default"]["provider"] == "memory"
