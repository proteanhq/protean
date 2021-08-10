# cSpell: disable

# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.coverage",
    "sphinx.ext.doctest",
    "sphinx.ext.extlinks",
    "sphinx.ext.ifconfig",
    "sphinx.ext.napoleon",
    "sphinx.ext.todo",
    "sphinx.ext.viewcode",
    "sphinx_tabs.tabs",
]
if os.getenv("SPELLCHECK"):
    extensions += "sphinxcontrib.spelling"
    spelling_show_suggestions = True
    spelling_lang = "en_US"

source_suffix = ".rst"
master_doc = "index"
project = "Protean"
year = "2021"
author = "Subhash Bhushan C"
copyright = "{0}, {1}".format(year, author)
version = release = "0.6.0"

pygments_style = "autumn"
templates_path = ["."]
extlinks = {
    "issue": ("https://github.com/proteanhq/protean/issues/%s", "#"),
    "pr": ("https://github.com/proteanhq/protean/pull/%s", "PR #"),
}
# on_rtd is whether we are on readthedocs.org
# on_rtd = os.environ.get('READTHEDOCS', None) == 'True'

# if not on_rtd:  # only set the theme if we're building docs locally
#     html_theme = 'alabaster'

# Change theme to Alabaster
html_theme = "alabaster"

html_theme_options = {
    "show_powered_by": False,
    "github_user": "proteanhq",
    "github_repo": "protean",
    "github_banner": True,
    "show_related": False,
}

html_show_sourcelink = False
html_use_smartypants = True
html_last_updated_fmt = "%b %d, %Y"
html_split_index = False
html_sidebars = {
    "**": ["globaltoc.html", "sourcelink.html", "searchbox.html"],
}
html_short_title = "%s-%s" % (project, version)

napoleon_use_ivar = True
napoleon_use_rtype = False
napoleon_use_param = False
