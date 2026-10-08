# --8<-- [start:full]
from flask import Flask, g

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

    domain.init(traverse=False)

    @app.before_request
    def push_context():
        if not has_domain_context():
            # Push up a Domain Context and keep it to pop later
            g.domain_context = domain.domain_context()
            g.domain_context.push()

    @app.teardown_request
    def pop_context(exc):
        # Pop the Domain Context this request pushed, even on an error
        context = g.pop("domain_context", None)
        if context is not None:
            context.pop(exc)

    return app


# --8<-- [end:full]
