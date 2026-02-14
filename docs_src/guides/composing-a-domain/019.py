import logging.config

from flask import Flask

from protean import Domain
from protean.domain.context import has_domain_context
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class User:
    first_name: Annotated[str, Field(max_length=50)] | None = None
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int | None = None


def create_app(config):
    app = Flask(__name__, static_folder=None)

    domain.config.from_object(config)
    logging.config.dictConfig(domain.config["LOGGING_CONFIG"])

    domain.init()

    @app.before_request
    def set_context():
        if not has_domain_context():
            # Push up a Domain Context
            domain.domain_context().push()

    @app.after_request
    def pop_context(response):
        # Pop the Domain Context
        domain.domain_context().pop()

        return response

    return app
