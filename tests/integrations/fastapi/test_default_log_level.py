"""A FastAPI app that calls ``domain.init()`` logs at INFO with no environment set."""

import logging
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean.domain import Domain
from protean.integrations.fastapi.health import create_health_router

pytestmark = pytest.mark.no_test_domain


@pytest.fixture(autouse=True)
def _restore_root_logger(monkeypatch):
    for var in ("PROTEAN_ENV", "ENV", "ENVIRONMENT", "PROTEAN_LOG_LEVEL"):
        monkeypatch.delenv(var, raising=False)
    root = logging.getLogger()
    original_handlers, original_level = root.handlers[:], root.level

    yield

    root.handlers[:] = original_handlers
    root.setLevel(original_level)


def test_app_that_inits_the_domain_logs_at_info(tmp_path):
    domain = Domain(root_path=str(tmp_path), name="FastAPIDefaultLevel")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        domain.init(traverse=False)
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(create_health_router(domain))
    # Auto-configuration skips when the root logger has handlers, and pytest
    # adds its own.
    logging.getLogger().handlers.clear()

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200

    assert logging.getLogger().level == logging.INFO
    assert logging.getLogger("protean").getEffectiveLevel() == logging.INFO
