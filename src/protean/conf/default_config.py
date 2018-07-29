"""
Default settings. Override these with settings in the module pointed to
by the PROTEAN_SETTINGS_MODULE environment variable.

Inspired, and guided, by Django's Settings Module.
Django doc reference: https://docs.djangoproject.com/en/2.0/topics/settings/
"""


####################
# CORE             #
####################

DEBUG = False

# A secret key for this particular Protean installation. Used in secret-key
# hashing algorithms.
SECRET_KEY = ''
