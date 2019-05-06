""" Module for defining the response Renderers """
# Protean
from flask import jsonify, make_response


def render_json(data, code, headers):
    """ Render the response as a JSON """

    resp = make_response(jsonify(data), code)
    resp.headers.extend(headers or {})

    return resp
