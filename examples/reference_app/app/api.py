"""FastAPI app for the reference application.

This wires the golden-path blog domain from ``examples/reference_app/blog.py``
to HTTP, SQLite, and a broker. Two endpoints cover the write-then-read arc the
demo prints on the console:

    POST /posts   create and publish a post (dispatches ``PublishPost``)
    GET  /posts   the published-posts feed (reads the projection)

Run it from ``examples/reference_app`` after installing the requirements:

    uvicorn app.api:app --reload

The domain is loaded by file path, not by package import: ``examples/`` is not
an installed package and ``blog.py`` sits one directory up. Loading it here
gives this process its own ``Domain`` instance and leaves ``blog.py``'s own
in-memory quickstart untouched.

The app's own ``domain.toml`` lives beside this file. ``blog.py`` builds its
domain with ``root_path`` fixed to ``blog.py``'s directory, and config
resolution only searches a directory and its two parents, never a subfolder, so
this config never leaks into the ``python blog.py`` quickstart. The lifespan
loads it explicitly and applies it before ``domain.init()``.
"""

import importlib.util
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from protean.domain.config import Config2
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)
from protean.utils.globals import current_domain

APP_DIR = os.path.dirname(os.path.abspath(__file__))
_BLOG_PATH = os.path.join(os.path.dirname(APP_DIR), "blog.py")


def _load_domain():
    """Load ``blog.py`` by file path and return its domain and elements."""
    spec = importlib.util.spec_from_file_location("reference_app_blog", _BLOG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not build a loadable module spec from {_BLOG_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_blog = _load_domain()
domain = _blog.domain
PublishPost = _blog.PublishPost
Post = _blog.Post
PublishedPostsFeed = _blog.PublishedPostsFeed


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Apply the app's own config (SQLite + broker) before init. Without this the
    # domain would run on the in-memory default it was built with, and nothing
    # would persist to SQLite.
    domain.config = Config2.load_from_path(APP_DIR)
    domain.init(traverse=False)
    with domain.domain_context():
        domain.setup_database()

    yield

    domain.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})
register_exception_handlers(app)


@app.post("/posts", status_code=201)
def create_post(payload: dict):
    """Create and publish a post, returning its id.

    A missing or empty title raises ``ValidationError`` when the command is
    built; the registered exception handlers turn that into a 400.

    Declared ``def``, not ``async def``: ``domain.process()`` is synchronous
    and writes to the database, so FastAPI runs it in a threadpool instead of
    blocking the event loop.
    """
    post_id = current_domain.process(PublishPost(**payload))
    return {"id": post_id}


@app.get("/posts")
def list_posts():
    """Return the published-posts feed from the projection.

    Synchronous for the same reason as ``create_post``: the projection query
    hits the database.
    """
    feed = current_domain.view_for(PublishedPostsFeed).query.all()
    return {
        "posts": [{"post_id": row.post_id, "title": row.title} for row in feed.items]
    }
