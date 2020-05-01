#!/usr/bin/env python
# -*- encoding: utf-8 -*-

"""Setup Module for Protean Application Framework"""

from __future__ import absolute_import, print_function

# Standard Library Imports
import io
import re

from glob import glob
from os.path import basename, dirname, join, splitext

# ThirdParty Library Imports
from setuptools import find_packages, setup


def read(*names, **kwargs):
    """Helper method to read files"""
    return io.open(
        join(dirname(__file__), *names),
        encoding=kwargs.get('encoding', 'utf8'),
    ).read()


setup(
    name='protean',
    version='0.5.0',
    license='BSD 3-Clause License',
    description='Protean Application Framework',
    long_description='%s\n%s' % (
        re.compile('^.. start-badges.*^.. end-badges', re.M | re.S).sub('', read('README.rst')),
        re.sub(':[a-z]+:`~?(.*?)`', r'``\1``', read('CHANGELOG.rst')),
    ),
    author='Subhash Bhushan C',
    author_email='subhash@team8solutions.com',
    url='https://github.com/proteanhq/protean',
    packages=find_packages('src'),
    package_dir={'': 'src'},
    py_modules=[splitext(basename(path))[0] for path in glob('src/*.py')],
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        # complete classifier list: http://pypi.python.org/pypi?%3Aaction=list_classifiers
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: Unix',
        'Operating System :: POSIX :: Linux',
        'Operating System :: OS/2',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    keywords=[
        # eg: 'keyword1', 'keyword2', 'keyword3',
    ],
    install_requires=[
        'click>=7.0',
        'cookiecutter>=1.7.0',
        'elasticsearch-dsl>=7.1.0',
        'flask>=1.1.1',
        'inflect>=4.1.0',
        'marshmallow>=3.5.1',
        'psycopg2>=2.8.4',
        'python-dateutil>=2.8.1',
        'rq>=1.3.0',
        'celery[redis]>=4.4.2',
        'sendgrid>=6.1.3',
        'sqlalchemy>=1.3.15',
        'werkzeug>=1.0.0',
    ],
    entry_points={
        'console_scripts': [
            'protean = protean.cli:main',
        ],
    },
)
