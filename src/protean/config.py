"""Package Configuration Module"""

import configparser
import os

BASEDIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

config = configparser.ConfigParser()
config.read(BASEDIR+'/config.ini')


class Config:
    """Base Configuration Class"""
    WTF_CSRF_ENABLED = True
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'p!yb*$xEbsR58n4f'
    PER_PAGE = 10


class DevelopmentConfig(Config):
    """Development Environment Configuration"""
    DEBUG = True


class TestConfig(Config):
    """Test Environment Configuration"""
    TESTING = True


class StagingConfig(Config):
    """Staging Environment Configuration"""
    DEBUG = False


class ProductionConfig(Config):
    """Production Environment Configuration"""
    DEBUG = False


ENV = os.environ.get('APPENV') or 'DEV'
CONFIG = None
if ENV == "TEST":
    CONFIG = TestConfig()
elif ENV == "PRODUCTION":
    CONFIG = ProductionConfig()
elif ENV == "STAGING":
    CONFIG = StagingConfig()
else:
    CONFIG = DevelopmentConfig()
