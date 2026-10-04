"""Prove rental/domain/ is importable with nothing but the standard library.

Importing `rental.domain.pricing` the ordinary way executes `rental/__init__.py`
first -- the phase-1 app factory, which imports Flask and SQLAlchemy at module
scope. That would report a leak no matter how pure the domain module is.

So we stand in a stub `rental` package pointing at the real directory. The real
__init__.py never runs; the domain module and everything it transitively imports
do. Anything framework-shaped that appears in sys.modules afterwards was pulled
in by the domain code itself, which is exactly the question.
"""

import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = ("flask", "sqlalchemy", "wtforms", "dotenv", "psycopg", "click")

sys.path.insert(0, str(ROOT))
stub = types.ModuleType("rental")
stub.__path__ = [str(ROOT / "rental")]
sys.modules["rental"] = stub

modules = sorted(p.stem for p in (ROOT / "rental" / "domain").glob("*.py") if p.stem != "__init__")
if not modules:
    raise SystemExit("no domain modules found -- wrong directory?")

for name in modules:
    importlib.import_module(f"rental.domain.{name}")

leaked = sorted(m for m in sys.modules if m.startswith(FORBIDDEN))
print("domain modules checked :", ", ".join(modules))
print("framework modules pulled in:", ", ".join(leaked) if leaked else "NONE")
if leaked:
    raise SystemExit(
        "rental/domain/ is no longer pure -- it pulled in: " + ", ".join(leaked)
    )
