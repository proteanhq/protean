"""The examples on the when-to-compose guide behave as the page says."""

import pytest
from fastapi.testclient import TestClient

from protean.domain.context import has_domain_context
from protean.utils.globals import current_domain
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_fastapi_middleware_pushes_a_domain_context_per_request():
    example = load_example("guides/compose-a-domain/when-to-compose/001.py")

    @example.app.get("/domain")
    def domain_name():
        return {"name": current_domain.name}

    response = TestClient(example.app).get("/domain")

    assert response.status_code == 200
    assert response.json() == {"name": "Tasks"}
    assert not has_domain_context()


def test_fastapi_maps_a_validation_error_to_400():
    example = load_example("guides/compose-a-domain/when-to-compose/001.py")

    @example.app.post("/tasks")
    def create_task():
        example.Task(title="x" * 201)

    response = TestClient(example.app).post("/tasks")

    assert response.status_code == 400
    assert "title" in response.json()["error"]


class FlaskConfig:
    DEBUG = True


def test_flask_pushes_a_context_per_request_and_pops_it_after():
    example = load_example("guides/compose-a-domain/019.py")
    app = example.create_app(FlaskConfig)

    @app.route("/user")
    def user():
        repo = current_domain.repository_for(example.User)
        repo.add(example.User(first_name="John", last_name="Doe", age=30))
        return {
            "in_context": has_domain_context(),
            "count": len(repo.query.all().items),
        }

    response = app.test_client().get("/user")

    assert response.status_code == 200
    assert response.json == {"in_context": True, "count": 1}
    assert not has_domain_context()
    assert example.domain.config["debug"] is True


def test_flask_pops_the_context_when_the_view_fails():
    example = load_example("guides/compose-a-domain/019.py")
    app = example.create_app(FlaskConfig)
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/fail")
    def fail():
        raise RuntimeError("boom")

    response = app.test_client().get("/fail")

    assert response.status_code == 500
    assert not has_domain_context()


def test_console_main_saves_a_task():
    example = load_example("guides/compose-a-domain/when-to-compose/002.py")

    example.main()

    with example.domain.domain_context():
        tasks = example.domain.repository_for(example.Task).query.all().items
    assert [task.title for task in tasks] == ["Write documentation"]
