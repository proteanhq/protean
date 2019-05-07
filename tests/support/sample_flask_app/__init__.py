""" Sample Protean Flask app for testing"""
# Protean
from flask import Flask
from protean.impl.api.flask.base import Protean

# Local/Relative Imports
from .blueprint import blueprint
from .views import (CreateDogResource, CurrentContextResource, DeleteDogResource, HumanResourceSet,
                    ListDogResource, ShowDogResource, UpdateDogResource, flask_view)

app = Flask(__name__)
api = Protean(app)

app.add_url_rule('/dogs/<int:identifier>',
                 view_func=ShowDogResource.as_view('show_dog'),
                 methods=['GET'])
app.add_url_rule('/dogs',
                 view_func=CreateDogResource.as_view('create_dog'),
                 methods=['POST'])
app.add_url_rule('/dogs',
                 view_func=ListDogResource.as_view('list_dogs'),
                 methods=['GET'])
app.add_url_rule('/dogs/<int:identifier>',
                 view_func=UpdateDogResource.as_view('update_dog'),
                 methods=['PUT'])
app.add_url_rule('/dogs/<int:identifier>',
                 view_func=DeleteDogResource.as_view('delete_dog'),
                 methods=['DELETE'])
app.add_url_rule('/flask-view', view_func=flask_view,
                 methods=['GET'])
app.add_url_rule('/current-context', methods=['GET'],
                 view_func=CurrentContextResource.as_view('current_context'))\

api.register_viewset(HumanResourceSet, 'humans', '/humans', pk_type='int',
                     additional_routes=['/<int:identifier>/my_dogs'])

app.register_blueprint(blueprint, url_prefix='/blueprint')
