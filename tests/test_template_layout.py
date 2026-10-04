"""Where templates may live, so that the deployment keeps them.

Vercel's build treats a directory named ``public`` as the static-assets
convention and strips it out of the serverless function bundle. A template
under such a directory is present in git, present locally, and simply absent
in production: every page that renders it returns 500 with
``TemplateNotFound``, while the rest of the site works perfectly. The tests
pass either way, because the tests run against the local filesystem.

This is the guard that turns that into a failing test instead of a live
outage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "rental" / "templates"

# Directory names the platform claims for itself. "public" is the one that bit
# us; the others are listed because the failure mode is silent and identical.
RESERVED_DIRECTORY_NAMES = {"public", "static", "api", "_next", ".well-known"}


def test_the_template_root_exists():
    """Guards the guard: a wrong path here would make everything below vacuous."""
    assert TEMPLATE_ROOT.is_dir(), TEMPLATE_ROOT


def test_templates_exist_to_be_checked():
    """A typo in the glob would let the directory rule pass over an empty set."""
    assert len(list(TEMPLATE_ROOT.rglob("*.html"))) > 20


@pytest.mark.parametrize("reserved", sorted(RESERVED_DIRECTORY_NAMES))
def test_no_template_lives_under_a_directory_the_platform_reserves(reserved):
    offenders = [
        str(path.relative_to(TEMPLATE_ROOT))
        for path in TEMPLATE_ROOT.rglob("*.html")
        if reserved in path.relative_to(TEMPLATE_ROOT).parts[:-1]
    ]
    assert not offenders, (
        f"These templates live under a directory named {reserved!r}, which Vercel "
        f"strips from the function bundle: {offenders}. Rename the directory -- a "
        "file whose NAME contains the word is fine, only the directory is reserved."
    )
