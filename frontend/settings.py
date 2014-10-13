"""Django settings for frontend project.

Two databases are configured for the use with django here. One for tko tables,
which will always be the same database for all instances (the global database),
and one for everything else, which will be the same as the global database for
the master, but a local database for shards.

This is implemented using a Django database router.
For more details on how the routing works, see db_router.py.
"""

import os
import common
from autotest_lib.client.common_lib import global_config

c = global_config.global_config
_section = 'AUTOTEST_WEB'

DEBUG = c.get_config_value(_section, "sql_debug_mode", type=bool, default=False)
TEMPLATE_DEBUG = c.get_config_value(_section, "template_debug_mode", type=bool,
                                    default=False)

FULL_ADMIN = False

ADMINS = (
    # ('Your Name', 'your_email@domain.com'),
)

MANAGERS = ADMINS

SHARD_HOSTNAME = c.get_config_value('SHARD', 'shard_hostname', default=None)

def _get_config(config_key, prefix='',
                default=global_config.global_config._NO_DEFAULT_SPECIFIED,
                type=str):
    """Retrieves a global config value for the specified key.

    @param config_key: The string key associated with the desired config value.
    @param prefix: If existing, the value with the key prefix + config_key
                   will be returned. If it doesn't exist, the normal key
                   is used for the lookup.
    @param default: The default value to return if the value couldn't be looked
                    up; neither for prefix + config_key nor config_key.
    @param type: Expected type of the return value.

    @return: The config value, as returned by
             global_config.global_config.get_config_value().
    """

    # When running on a shard, fail loudly if the global_db_ prefixed settings
    # aren't present.
    if SHARD_HOSTNAME:
        return c.get_config_value(_section, prefix + config_key,
                                  default=default, type=type)

    return c.get_config_value_with_fallback(_section, prefix + config_key,
                                            config_key, default=default,
                                            type=type)


def _get_database_config(config_prefix=''):
    """Create a configuration dictionary that can be passed to Django.

    @param config_prefix: If specified, this function will try to prefix lookup
                          keys from global_config with this. If those values
                          don't exist, the normal key without the prefix will
                          be used.

    @return A dictionary that can be used in the Django DATABASES setting.
    """
    config = {
        'ENGINE': 'autotest_lib.frontend.db.backends.afe',
        'PORT': '',
        'HOST': _get_config("host", config_prefix),
        'NAME': _get_config("database", config_prefix),
        'USER': _get_config("user", config_prefix),
        'PASSWORD': _get_config("password", config_prefix, default=''),
        'READONLY_HOST': _get_config(
                "readonly_host", config_prefix,
                default=_get_config("host", config_prefix)),
        'READONLY_USER': _get_config(
                "readonly_user", config_prefix,
                default=_get_config("user", config_prefix)),
        'OPTIONS': {
            'timeout': _get_config("query_timeout", config_prefix,
                                   type=int, default=3600)
        }
    }
    if config['READONLY_USER'] != config['USER']:
        config['READONLY_PASSWORD'] = _get_config(
                'readonly_password', config_prefix, default='')
    else:
        config['READONLY_PASSWORD'] = config['PASSWORD']
    return config


AUTOTEST_DEFAULT = _get_database_config()
AUTOTEST_GLOBAL = _get_database_config('global_db_')

ALLOWED_HOSTS = '*'

DATABASES = {'default': AUTOTEST_DEFAULT, 'global': AUTOTEST_GLOBAL}

# Have to set SECRET_KEY before importing connections because of this bug:
# https://code.djangoproject.com/ticket/20704
# TODO: Order this again after an upgrade to Django 1.6 or higher.
# Make this unique, and don't share it with anybody.
SECRET_KEY = 'pn-t15u(epetamdflb%dqaaxw+5u&2#0u-jah70w1l*_9*)=n7'

# Do not do this here or from the router, or most unit tests will fail.
# from django.db import connection

DATABASE_ROUTERS = ['autotest_lib.frontend.db_router.Router']

# prefix applied to all URLs - useful if requests are coming through apache,
# and you need this app to coexist with others
URL_PREFIX = 'afe/server/'
TKO_URL_PREFIX = 'new_tko/server/'
CROSCHART_URL_PREFIX = 'croschart/server/'

# Local time zone for this installation. Choices can be found here:
# http://www.postgresql.org/docs/8.1/static/datetime-keywords.html#DATETIME-TIMEZONE-SET-TABLE
# although not all variations may be possible on all operating systems.
# If running in a Windows environment this must be set to the same as your
# system time zone.
TIME_ZONE = 'America/Los_Angeles'

# Language code for this installation. All choices can be found here:
# http://www.w3.org/TR/REC-html40/struct/dirlang.html#langcodes
# http://blogs.law.harvard.edu/tech/stories/storyReader$15
LANGUAGE_CODE = 'en-us'

SITE_ID = 1

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# Absolute path to the directory that holds media.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = ''

# URL that handles the media served from MEDIA_ROOT.
# Example: "http://media.lawrence.com"
MEDIA_URL = ''

# URL prefix of static file. Only used by the admin interface.
STATIC_URL = '/' + URL_PREFIX + 'admin/'

# URL prefix for admin media -- CSS, JavaScript and images. Make sure to use a
# trailing slash.
# Examples: "http://foo.com/media/", "/media/".
ADMIN_MEDIA_PREFIX = '/media/'

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
#     'django.template.loaders.eggs.Loader',
)

MIDDLEWARE_CLASSES = (
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'frontend.apache_auth.ApacheAuthMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.middleware.doc.XViewMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'frontend.shared.json_html_formatter.JsonToHtmlMiddleware',
)

ROOT_URLCONF = 'frontend.urls'

TEMPLATE_DIRS = (
    # Put strings here, like "/home/html/django_templates" or "C:/www/django/templates".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.

    os.path.abspath(os.path.dirname(__file__) + '/templates'),
    os.path.abspath(os.path.dirname(__file__) + '/croschart/templates'),
    os.path.abspath(os.path.dirname(__file__) + '/perf-dashboard/templates')
)

INSTALLED_APPS = (
    'frontend.afe',
    'frontend.tko',
    'frontend.croschart',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
)

AUTHENTICATION_BACKENDS = (
    'frontend.apache_auth.SimpleAuthBackend',
)
# TODO(scottz): Temporary addition until time can be spent untangling middleware
# session crosbug.com/31608
SESSION_COOKIE_AGE = 1200

AUTOTEST_CREATE_ADMIN_GROUPS = True