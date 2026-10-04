"""Entry point.

Vercel's zero-config Flask support looks for a top-level ``app.py`` exporting a
Flask instance named ``app``. Running ``flask run`` locally finds it here too.
"""

from rental import create_app

app = create_app()
