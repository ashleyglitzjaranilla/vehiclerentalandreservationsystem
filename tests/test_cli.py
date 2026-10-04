"""The database CLI: reset-db, seed and create-admin."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from rental.db import get_session
from rental.models import Maintenance, RentalRates, User, Vehicle

ARGS = ("--password", "adminpass1", "--demo-password", "demopass1")


def run(app, *args):
    return app.test_cli_runner().invoke(args=list(args))


def test_reset_db_seeds_a_usable_demo_database(app):
    result = run(app, "reset-db", *ARGS)
    assert result.exit_code == 0

    with app.app_context():
        db = get_session()
        assert db.scalar(select(func.count()).select_from(Vehicle)) == 10
        assert db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) == 1
        assert db.scalar(select(func.count()).select_from(User).where(User.role == "customer")) == 3
        assert db.scalar(select(func.count()).select_from(Maintenance)) == 1
        assert RentalRates.current(db).insurance_fee_per_day == Decimal("300.00")


def test_the_seeded_maintenance_vehicle_is_marked_under_maintenance(app):
    run(app, "reset-db", *ARGS)

    with app.app_context():
        db = get_session()
        record = db.scalars(select(Maintenance)).first()
        assert db.get(Vehicle, record.vehicle_id).status == "MAINTENANCE"


def test_the_requirements_demo_vehicles_are_present_with_their_rates(app):
    run(app, "reset-db", *ARGS)

    with app.app_context():
        db = get_session()
        vios = db.scalars(select(Vehicle).where(Vehicle.model == "Vios")).one()
        assert vios.daily_rate == Decimal("1500.00")
        assert vios.vehicle_type == "Sedan"

        hiace = db.scalars(select(Vehicle).where(Vehicle.model == "HiAce")).one()
        assert hiace.seats == 12
        assert hiace.transmission == "Manual"
        assert hiace.daily_rate == Decimal("3500.00")


def test_the_seeded_admin_can_sign_in(app):
    run(app, "reset-db", *ARGS)

    response = app.test_client().post(
        "/login", data={"username": "admin", "password": "adminpass1"}
    )
    assert response.status_code == 302


def test_seeding_twice_adds_nothing_the_second_time(app):
    run(app, "reset-db", *ARGS)
    result = run(app, "seed", "--password", "adminpass1", "--demo-password", "demopass1")

    with app.app_context():
        assert get_session().scalar(select(func.count()).select_from(Vehicle)) == 10
    assert result.exit_code == 0


def test_reset_db_refuses_a_non_sqlite_database_without_yes(app):
    app.config["DATABASE_URL"] = "postgresql+psycopg://user:pw@example.com/db"
    result = run(app, "reset-db", "--password", "adminpass1", "--demo-password", "demopass1")
    assert result.exit_code != 0
    assert "refusing" in result.output.lower()


def test_reset_db_refuses_a_scheme_that_merely_starts_with_sqlite(app):
    """A bare prefix check would let "sqlite_evil://" through.

    Nothing should rely on create_engine() raising NoSuchModuleError to stop a
    destructive command -- the guard has to refuse on its own.
    """
    app.config["DATABASE_URL"] = "sqlite_evil://realprodhost/db"
    result = run(app, "reset-db", "--password", "adminpass1", "--demo-password", "demopass1")
    assert result.exit_code != 0
    assert "refusing" in result.output.lower()


def test_reset_db_still_allows_a_driver_qualified_sqlite_url(app):
    """SQLAlchemy URLs may carry a driver suffix; sqlite+pysqlite is still SQLite."""
    app.config["DATABASE_URL"] = "sqlite+pysqlite://"
    result = run(app, "reset-db", "--password", "adminpass1", "--demo-password", "demopass1")
    assert result.exit_code == 0
