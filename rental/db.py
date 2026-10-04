"""Database engine creation and per-request session handling.

The app talks to Neon Postgres in production and falls back to a local SQLite
file when ``DATABASE_URL`` is not set, so it can be run with zero configuration
while it is being developed.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, g
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

# Used when no DATABASE_URL is provided (local development / demos). The two
# spellings must agree: the URL is what SQLAlchemy connects to, the path is what
# we check for before deciding the fallback is safe.
DEFAULT_SQLITE_FILE = "rental.db"
DEFAULT_SQLITE_URL = f"sqlite:///{DEFAULT_SQLITE_FILE}"


def get_database_url() -> str:
    """Return the database URL to connect to, normalised for the psycopg 3 driver.

    Reads ``DATABASE_URL`` from the environment. Neon (like Heroku) hands out
    connection strings that start with ``postgres://`` or ``postgresql://``;
    SQLAlchemy needs an explicit driver, so both forms are rewritten to
    ``postgresql+psycopg://``. When the variable is empty or missing we fall
    back to a local SQLite file -- but only when we are actually running
    locally.

    On Vercel that fallback is a trap rather than a convenience. A deployment
    with no ``DATABASE_URL`` starts cleanly and serves every page that only
    renders a form, then returns 500 on every page that runs a query, because
    the SQLite file it invented has no tables in it. The symptom looks like a
    code defect and is not one, so we refuse the fallback and say what is
    actually wrong.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        # The fallback may resume an existing local database; it may never
        # invent one. Keying this off a platform variable such as VERCEL was
        # too fragile -- that one only exists when the project exposes system
        # environment variables, which is a setting that can be turned off. A
        # missing file is a misconfiguration on any host, so this rule needs no
        # help from the platform to be right.
        if not Path(DEFAULT_SQLITE_FILE).exists():
            raise RuntimeError(
                f"DATABASE_URL is not set and there is no {DEFAULT_SQLITE_FILE} to "
                "fall back to. Refusing to create an empty database, which would "
                "start normally and then fail on every page that reads a vehicle. "
                "On Vercel: set DATABASE_URL in the project's Environment "
                "Variables for the Production environment, then REDEPLOY -- a "
                "deployment only sees the variables that existed when it was "
                "created. Locally: run `flask reset-db` to create the file."
            )
        return DEFAULT_SQLITE_URL
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def create_db_engine(url: str) -> Engine:
    """Build the SQLAlchemy engine for the given URL.

    On Postgres we use ``NullPool`` because each Vercel serverless invocation is
    short-lived and must not hold connections open, and ``pool_pre_ping`` so a
    connection dropped by Neon is discarded instead of raising. In-memory SQLite
    needs the opposite treatment: a single shared connection, otherwise every
    checkout would see a brand new empty database (this is what the tests use).
    """
    if url.startswith("sqlite"):
        is_memory = ":memory:" in url or url in ("sqlite://", "sqlite:///:memory:")
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if is_memory else None,
        )
    return create_engine(url, poolclass=NullPool, pool_pre_ping=True)


def init_app(app: Flask) -> None:
    """Attach an engine and session factory to the app and close sessions on teardown."""
    engine = create_db_engine(app.config["DATABASE_URL"])
    app.extensions["db_engine"] = engine
    app.extensions["db_session_factory"] = sessionmaker(bind=engine, expire_on_commit=False)
    app.teardown_appcontext(close_session)


def get_engine() -> Engine:
    """Return the engine belonging to the current application."""
    from flask import current_app

    return current_app.extensions["db_engine"]


def get_session() -> Session:
    """Return the SQLAlchemy session for the current request or CLI command.

    The session is created on first use and stored on Flask's ``g`` object, so
    every part of a single request shares one session and one transaction. It is
    closed automatically when the request finishes (see :func:`close_session`).
    """
    from flask import current_app

    if "db_session" not in g:
        g.db_session = current_app.extensions["db_session_factory"]()
    return g.db_session


def close_session(exception: BaseException | None = None) -> None:
    """Close the session at the end of a request, rolling back if something failed."""
    session = g.pop("db_session", None)
    if session is None:
        return
    if exception is not None:
        session.rollback()
    session.close()
