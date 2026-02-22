import logging.config

from flask import Flask

from protean import Domain
from protean.domain.context import has_domain_context
from protean.fields import Integer, String

domain = Domain()


@domain.aggregate
class User:
    first_name: String(max_length=50)
    last_name: String(max_length=50)
    age: Integer()


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
