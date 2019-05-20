"""Module to test request data parsing functionality"""
# Standard Library Imports
import json

from io import BytesIO

# Protean
from flask import jsonify, request
from protean.impl.api.flask.views import APIResource
from tests.old.support.sample_flask_app import app
from werkzeug.datastructures import FileStorage


class DummyView(APIResource):
    """ Dummy view for testing the requests """
    methods = ['GET', 'POST', 'PUT']

    def get(self):
        """ Return the query params as the payload"""
        return jsonify(request.payload)

    def post(self):
        """ Return the form data/json as the payload"""
        for key, val in request.payload.items():
            if isinstance(val, FileStorage):
                request.payload[key] = val.filename
        return jsonify(request.payload)

    def put(self):
        """ Return the form data/json as the payload"""
        return jsonify(request.payload)


app.add_url_rule('/dummy', view_func=DummyView.as_view('dummy'))


class TestRequestParsing:
    """Tests for parsing of requests"""

    @classmethod
    def setup_class(cls):
        """ Setup for this test case"""

        # Create the test client
        cls.client = app.test_client()

        cls.payload = {'name': 'Harry', 'tags': [1, 2]}

    def test_form_type(self):
        """ Test parsing data when there is no content type """
        rv = self.client.post('/dummy', data=self.payload,
                              content_type=None)
        assert rv.status_code == 200

        payload = {'name': 'Harry', 'tags': ['1', '2']}
        assert rv.json == payload

    def test_default_type(self):
        rv = self.client.post('/dummy', data=json.dumps(self.payload),
                              content_type=None)
        assert rv.status_code == 200
        assert rv.json == self.payload

    def test_json_type(self):
        rv = self.client.post('/dummy', data=json.dumps(self.payload),
                              content_type='application/json')
        assert rv.status_code == 200
        assert rv.json == self.payload

    def test_query_params(self):
        rv = self.client.get('/dummy', query_string=self.payload)
        assert rv.status_code == 200

        payload = {'name': 'Harry', 'tags': ['1', '2']}
        assert rv.json == payload

    def test_multipart_type(self):
        """ Test parsing data when there is no content type """
        m_payload = {
            'file': (BytesIO(b'my file contents'), 'test file.txt')
        }
        m_payload.update(self.payload)
        rv = self.client.post('/dummy', data=m_payload,
                              content_type='multipart/form-data')
        assert rv.status_code == 200

        payload = {'name': 'Harry', 'tags': ['1', '2'],
                   'file': 'test file.txt'}
        assert rv.json == payload
