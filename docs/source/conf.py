# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
# docs/source/conf.py — top of the file (replace existing top)
import os
import sys
from sphinx.errors import ConfigError

CONF_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CONF_DIR, "..", ".."))

sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bookmanager.settings")

try:
    import django
    django.setup()
except Exception as exc:
    raise ConfigError(
        "Failed to import Django or configure settings. "
        "Check DJANGO_SETTINGS_MODULE and that the project root "
        f"({PROJECT_ROOT}) is on sys.path. Original error: {exc}"
    )

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Book Library'
title = "Code Documentation"
author = 'Mihalcea Marius-Alex'
copyright = f'2025, {author}'
version = release = '1.0'


# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx_autodoc_typehints",
    "sphinx.ext.viewcode",
    "rst2pdf.pdfbuilder",
]

templates_path = ['_templates']
exclude_patterns = []

# -- Options for HTML -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output
html_theme = "sphinx_rtd_theme"
html_static_path = ['_static']
html_theme_options = {
    'collapse_navigation': False,
    'navigation_depth': 6,
    'titles_only': False,
}

# -- Options for autodoc -------------------------------------------------
autodoc_class_signature = 'separated'
autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'undoc-members': True,
    'show-inheritance': True,
    'inherited-members': False,
}
autodoc_member_order = 'bysource'
autodoc_mock_imports = ["django"]
autodoc_typehints = 'description'

# -- Options for intersphinx -------------------------------------------------
intersphinx_mapping = {
    "python": ('https://docs.python.org/3', None),
    "django": ("https://docs.djangoproject.com/en/stable/", "https://docs.djangoproject.com/en/stable/_objects/"),
}

# -- Options for nitpicky -------------------------------------------------
nitpicky = True
nitpick_ignore = [
    ("py:class", "django.contrib.admin.options.ModelAdmin"),
    ("py:class", "django.db.models.base.Model"),
    ("py:class", "django.forms.forms.Form"),
    ("py:class", "django.forms.BaseInlineFormSet"),
    ("py:class", "django.forms.models.ModelForm"),
    ("py:class", "django.apps.config.AppConfig"),
    ("py:class", "django.contrib.admin.options.TabularInline"),
    ("py:class", "django.core.management.base.BaseCommand"),
    ("py:class", "django.shortcuts.render"),
    ("py:class", "adminsortable2.admin.SortableInlineAdminMixin"),
    ("py:class", "adminsortable2.admin.SortableAdminBase"),
    ("py:class", "auditlog.models.LogEntry"),
    ("py:meth", "django.db.models.Manager.get_or_create"),
]

# -- Options for PDF output ----------------------------------------------------
pdf_documents = [
    ('index',
     f'{project} - {title}',
     f'{project} - {title}',
     f'{author}'),
]

pdf_fit_mode = "shrink"
pdf_stylesheets = ['sphinx', 'a4']

pdf_font_path = ['C:/Windows/Fonts']
pdf_style_path = []
pdf_use_toc = True
pdf_use_index = True
pdf_use_coverpage = True

# -- Options for autosummary  ----------------------------------------------------
autosummary_generate = True
