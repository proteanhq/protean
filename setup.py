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
        join(dirname(__file__), *names), encoding=kwargs.get("encoding", "utf8"),
    ).read()


elasticsearch_requires = ["elasticsearch>=7.13.1", "elasticsearch-dsl>=7.3.0"]
redis_requires = ["redis==3.5.2"]
sqlite_requires = ["sqlalchemy>=1.4.9"]
postgresql_requires = ["psycopg2>=2.8.4", "sqlalchemy>=1.4.1"]
celery_requires = ["celery[redis]~=4.4.2"]
sendgrid_requires = ["sendgrid>=6.1.3"]
flask_requires = ["flask>=1.1.1"]
marshmallow_requires = ["marshmallow>=3.5.1"]

install_requires = marshmallow_requires + [
    "click>=7.0",
    "cookiecutter>=1.7.0",
    "inflection>=0.5.1",
    "python-dateutil>=2.8.1",
    "werkzeug>=1.0.0",
]

all_external_requires = [
    elasticsearch_requires
    + redis_requires
    + postgresql_requires
    + celery_requires
    + sendgrid_requires
    + flask_requires
    + marshmallow_requires
]

testing_requires = all_external_requires + [
    "mock==4.0.2",
    "passlib==1.7.2",
    "pluggy==0.13.1",
    "pyjwt==1.7.1",
    "pytest-asyncio>=0.15.1",
    "pytest-cov==2.8.1",
    "pytest-flake8>=1.0.7",
    "pytest-mock==3.1.0",
    "pytest>=5.4.2",
]

docs_requires = [
    "livereload>=2.6.3",
    "sphinx==3.0.3",
    "sphinx_rtd_theme==0.4.3",
    "sphinx-tabs>=3.1.0",
]

dev_requires = (
    docs_requires
    + testing_requires
    + [
        "black==19.10b0",
        "check-manifest==0.42",
        "coverage==5.1",
        "docutils==0.16",
        "pre-commit==2.6.0",
        "tox==3.15.0",
        "twine==3.1.1",
    ]
)

setup(
    name="protean",
    version="0.6.1",
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
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
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
