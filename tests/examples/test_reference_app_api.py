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

        Setting ``DATABASE_URL`` before the lifespan runs makes the app's
        ``domain.toml`` resolve to this temp file, so the run is isolated and
        re-runnable. Entering the ``with`` block runs startup (init +
        setup_database); leaving it runs shutdown.
        """
        db_path = tmp_path / "reference_app.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

        api = _load_module("reference_app_api", _API_PATH)
        with TestClient(api.app) as client:
            # The lifespan has run: confirm the app is actually on SQLite, not
            # the in-memory default it was built with.
            assert api.domain.config["databases"]["default"]["provider"] == "sqlite"
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

    def test_app_config_does_not_leak_into_the_quickstart(self):
        """The app's SQLite config must not change what ``blog.py`` resolves.

        ``blog.py`` builds its ``Domain`` with ``root_path`` fixed to its own
        directory, and config resolution never descends into the ``app``
        subfolder. So importing the quickstart still resolves the in-memory
        default, even with the app's ``domain.toml`` present.
        """
        blog = _load_module("reference_app_blog", _BLOG_PATH)
        assert blog.domain.config["databases"]["default"]["provider"] == "memory"
