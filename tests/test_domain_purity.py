"""Run the domain-purity guard as part of the suite.

`scripts/check-domain-purity.py` is the check for this phase's defining
constraint -- that `rental/domain/` never imports Flask, SQLAlchemy or
`rental.models`/`rental.db` -- but until now nothing invoked it except a human
remembering to. A framework import (or a `rental.models` import) slipping into
a domain module passed the full 204-test suite; only running the script by
hand caught it. This test makes that check part of `pytest`, so CI (and every
future run of the suite) enforces it automatically.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check-domain-purity.py"


def test_domain_modules_stay_pure():
    """`rental/domain/` must import nothing but the standard library.

    Run with `cwd=REPO_ROOT` so the script's own path resolution (and this
    test) behaves the same no matter what directory pytest was invoked from.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "scripts/check-domain-purity.py failed -- a domain module pulled in "
        "something outside the standard library:\n\n"
        f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
    )
