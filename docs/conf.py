import os
import sys

sys.path.insert(0, os.path.abspath('..'))

project = 'PDT'
copyright = '2026, Dobrawa Rumszewicz'
author = 'Dobrawa Rumszewicz'
release = '1.0'


extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon'
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
language = 'pl'


html_theme = 'sphinx_rtd_theme'

html_static_path = ['_static']