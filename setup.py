#!/usr/bin/env python
# -*- encoding: utf-8 -*-

"""Setup Module for Protean Application Framework"""

from __future__ import absolute_import, print_function

import io
import re

from glob import glob
from os.path import basename, dirname, join, splitext

from setuptools import find_packages, setup


def read(*names, **kwargs):
    """Helper method to read files"""
    return io.open(
        join(dirname(__file__), *names),
        encoding=kwargs.get("encoding", "utf8"),
    ).read()


# Elasticsearch is tied to version 7.x because while 8.x supports sync and async workflows
#   in the same client, it introduces breaking changes in the API.
elasticsearch_requires = ["elasticsearch~=7.17.9", "elasticsearch-dsl~=7.4.1"]

redis_requires = ["redis==3.5.2"]
sqlite_requires = ["sqlalchemy~=1.4.50"]
postgresql_requires = ["psycopg2>=2.9.9", "sqlalchemy~=1.4.50"]
celery_requires = ["celery[redis]~=5.2.7"]
sendgrid_requires = ["sendgrid>=6.1.3"]
flask_requires = ["flask>=1.1.1"]
marshmallow_requires = ["marshmallow>=3.15.0"]
message_db_requires = ["message-db-py>=0.1.2"]

install_requires = marshmallow_requires + [
    "bleach>=4.1.0",
    "click>=7.0",
    "cookiecutter>=1.7.0",
    "copier>=6.1.0",
    "inflection>=0.5.1",
    "python-dateutil>=2.8.2",
    "werkzeug>=2.0.0",
]

all_external_requires = [
    elasticsearch_requires
    + redis_requires
    + postgresql_requires
    + celery_requires
    + sendgrid_requires
    + flask_requires
    + marshmallow_requires
    + message_db_requires
]

testing_requires = all_external_requires + [
    "autoflake>=2.2.1",
    "isort>=5.12.0",
    "mock==5.1.0",
    "pluggy==1.3.0",
    "pytest-asyncio>=0.21.1",
    "pytest-cov>=4.1.0",
    "pytest-flake8>=1.1.1",
    "pytest-mock==3.12.0",
    "pytest>=7.4.3",
]

docs_requires = [
    "livereload>=2.6.3",
    "sphinx>=7.2.6",
    "sphinx-tabs>=3.4.4",
]

types_requires = [
    "types-mock>=0.1.3",
    "types-python-dateutil>=0.1.6",
    "types-redis>=3.5.4",
    "types-Werkzeug>=1.0.5",
]

dev_requires = (
    docs_requires
    + types_requires
    + testing_requires
    + [
        "black>=23.11.0",
        "check-manifest>=0.49",
        "coverage>=7.3.2",
        "docutils>=0.18.0",
        "pre-commit>=2.16.0",
        "tox>=4.11.3",
        "twine>=4.0.2",
    ]
)

setup(
    name="protean",
    version="0.10.0",
    license="BSD 3-Clause License",
    description="Protean Application Framework",
    long_description="%s\n%s"
    % (
        re.compile("^.. start-badges.*^.. end-badges", re.M | re.S).sub(
            "", read("README.rst")
        ),
        re.sub(":[a-z]+:`~?(.*?)`", r"``\1``", read("CHANGELOG.rst")),
    ),
    author="Subhash Bhushan C",
    author_email="subhash@team8solutions.com",
    url="https://github.com/proteanhq/protean",
    packages=find_packages("src"),
    package_dir={"": "src"},
    py_modules=[splitext(basename(path))[0] for path in glob("src/*.py")],
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        # complete classifier list: http://pypi.python.org/pypi?%3Aaction=list_classifiers
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Software Development :: Libraries",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords=["domain-driven design", "ddd", "cqrs", "cqs", "ports and adapters"],
    install_requires=install_requires,
    extras_require={
        "elasticsearch": elasticsearch_requires,
        "redis": redis_requires,
        "postgresql": postgresql_requires,
        "sqlite": sqlite_requires,
        "celery": celery_requires,
        "sendgrid": sendgrid_requires,
        "flask": flask_requires,
        "marshmallow": marshmallow_requires,
        "message_db": message_db_requires,
        "external": all_external_requires,
        "test": testing_requires,
        "tests": testing_requires,
        "testing": testing_requires,
        "dev": dev_requires,
        "docs": docs_requires,
        "all": dev_requires,
    },
    entry_points={"console_scripts": ["protean = protean.cli:main"]},
)
