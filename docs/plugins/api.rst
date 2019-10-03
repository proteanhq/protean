.. _plugin-api:

==============
API frameworks
==============

Protean can be plugged into any API framework of your choice. Below are some recipes to plug Protean into known frameworks.

Flask
=====

.. code-block:: python

    import logging.config
    import os

    from flask import Flask

    from vfc.domain import domain


    def create_app():
        app = Flask(__name__, static_folder=None)

        # Configure domain
        current_path = os.path.abspath(os.path.dirname(__file__))
        config_path = os.path.join(current_path, "./../config.py")
        domain.config.from_pyfile(config_path)

        logging.config.dictConfig(domain.config['LOGGING_CONFIG'])

        from vfc.api.views.registration import registration_api
        from vfc.api.views.user import user_api
        app.register_blueprint(registration_api)
        app.register_blueprint(user_api)

        @app.before_request
        def set_context():
            # Push up a Domain Context
            # This should be done within Flask App
            context = domain.domain_context()
            context.push()

        return app
