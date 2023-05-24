# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
import warnings
sys.path.insert(0, os.path.abspath('..'))

import enigmatoolbox

# -- Project information -----------------------------------------------------

project = 'ENIGMA TOOLBOX'
copyright = '2020, enigmators'
author = 'Sara Larivière, Boris Bernhardt'


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = ['sphinx_tabs.tabs', 
              'sphinx.ext.autodoc',
              'sphinx.ext.autosectionlabel', 
              'sphinx.ext.autosummary',
              #'sphinx.ext.doctest',
              #'sphinx.ext.intersphinx',
              #sphinx.ext.mathjax',
              'sphinx.ext.napoleon',
              'sphinx.ext.viewcode',
              #'sphinxarg.ext',
              ]

autosummary_generate = True
autodoc_default_options = {'members': True, 'inherited-members': True}
numpydoc_show_class_members = False
autoclass_content = "class"


# The master toctree document.
master_doc = 'index'

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []

highlight_language ='none'

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'sphinx_rtd_theme'

html_theme_options = { 'style_nav_header_background': '#259595'}


# The name of the Pygments (syntax highlighting) style to use.
from pygments.styles import get_all_styles
pygments_style = 'enigmalexer'


# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

#def setup(app):
#    app.add_stylesheet('css/saratheriver_enigma.css')  # may also be an URL

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

# These paths are either relative to html_static_path
# or fully qualified paths (eg. https://...)
html_css_files = ['css/saratheriver_enigma.css', 
                  'css/saratheriver_nomaxwidth.css']

#html_style = 'css/saratheriver_enigma.css'

# add custom files that are stored in _static
def setup(app):
   app.add_css_file('css/saratheriver_tabs.css')