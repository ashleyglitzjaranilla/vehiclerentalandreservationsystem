"""Flask CLI commands for setting the database up.

Tables are deliberately never created when the app starts: on Vercel the app is
imported on every cold start, and running DDL there would be slow and unsafe.
These commands are run by hand from a laptop instead, pointed at Neon.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse

import click
from flask import Flask, current_app
from flask.cli import with_appcontext
from sqlalchemy import select

from .clock import today
from .db import get_engine, get_session
from .models import Base, Maintenance, RentalRates, User, Vehicle

# Ten vehicles for demos and screenshots. The first four are the ones the
# requirements name by rate; the rest fill out the body styles so the storefront
# filters have something to bite on.
SAMPLE_VEHICLES = [
    ("ABC 1234", "Toyota", "Vios", 2024, "Sedan", 5, "Automatic", "Gasoline", "1500.00", "250.00", "Silver", "AVAILABLE", "Economical city sedan, easy to park."),
    ("XYZ 5678", "Mitsubishi", "Mirage", 2023, "Hatchback", 5, "Automatic", "Gasoline", "1300.00", "220.00", "Red", "AVAILABLE", "Our most fuel-efficient hatchback."),
    ("JKL 2468", "Toyota", "Innova", 2023, "MPV", 7, "Automatic", "Diesel", "2500.00", "400.00", "Black", "AVAILABLE", "Seven seats, ideal for family trips."),
    ("MNO 1357", "Toyota", "HiAce", 2022, "Van", 12, "Manual", "Diesel", "3500.00", None, "White", "AVAILABLE", "Twelve-seater van for group travel."),
    ("PQR 8642", "Honda", "Civic", 2024, "Sedan", 5, "Automatic", "Gasoline", "2000.00", "320.00", "Blue", "AVAILABLE", "Comfortable executive sedan."),
    ("STU 9753", "Mitsubishi", "Montero Sport", 2023, "SUV", 7, "Automatic", "Diesel", "3000.00", "480.00", "Pearl White", "AVAILABLE", "Full-size SUV with plenty of luggage room."),
    ("VWX 3141", "Ford", "Ranger", 2023, "Pickup", 5, "Automatic", "Diesel", "2800.00", None, "Grey", "AVAILABLE", "Four-wheel-drive pickup for rough roads."),
    ("YZA 5926", "Suzuki", "Ertiga", 2022, "MPV", 7, "Manual", "Gasoline", "1800.00", "300.00", "Maroon", "AVAILABLE", "Compact seven-seater."),
    ("BCD 5358", "Nissan", "Urvan", 2021, "Van", 15, "Manual", "Diesel", "3800.00", None, "White", "AVAILABLE", "Fifteen-seater, driver available on request."),
    ("EFG 9793", "Hyundai", "Accent", 2022, "Sedan", 5, "Manual", "Diesel", "1400.00", "230.00", "White", "MAINTENANCE", "Currently in the workshop."),
]

SAMPLE_CUSTOMERS = [
    ("maria", "maria.santos@example.com", "Maria Santos", "0917 555 0101"),
    ("juan", "juan.delacruz@example.com", "Juan dela Cruz", "0917 555 0102"),
    ("ana", "ana.reyes@example.com", "Ana Reyes", "0917 555 0103"),
]


def register_cli(app: Flask) -> None:
    """Attach the custom database commands to the Flask app."""
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_admin_command)
    app.cli.add_command(seed_command)
    app.cli.add_command(reset_db_command)


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Create every table if it does not exist yet."""
    Base.metadata.create_all(get_engine())
    click.echo("Tables created.")


@click.command("create-admin")
@click.option("--username", prompt=True, help="Username for the new account.")
@click.option("--email", prompt=True, help="Email address for the new account.")
@click.password_option(help="Password for the new account.")
@with_appcontext
def create_admin_command(username: str, email: str, password: str):
    """Create an admin login account, storing the password as a werkzeug hash."""
    db = get_session()
    username = username.strip()
    email = email.strip().lower()

    if db.scalars(select(User).where(User.username == username)).first():
        click.echo(f"User {username!r} already exists.")
        return

    if db.scalars(select(User).where(User.email == email)).first():
        click.echo(f"Email {email!r} is already used by another account.")
        return

    user = User(username=username, email=email, role="admin")
    user.set_password(password)
    db.add(user)
    db.commit()
    click.echo(f"Created admin {username!r}.")


def seed_everything(db, admin_password: str, demo_password: str) -> dict[str, int]:
    """Insert the demo fleet, the accounts and the fee schedule. Idempotent.

    Anything already present by its unique key is skipped, so running this over
    a partly-populated database tops it up rather than failing.
    """
    counts = {"vehicles": 0, "customers": 0, "admins": 0, "maintenance": 0}

    RentalRates.current(db)

    if db.scalars(select(User).where(User.username == "admin")).first() is None:
        admin = User(
            username="admin",
            email="admin@example.com",
            role="admin",
            full_name="Fleet Administrator",
        )
        admin.set_password(admin_password)
        db.add(admin)
        counts["admins"] += 1

    for username, email, full_name, phone in SAMPLE_CUSTOMERS:
        if db.scalars(select(User).where(User.username == username)).first() is not None:
            continue
        customer = User(
            username=username, email=email, role="customer", full_name=full_name, phone=phone
        )
        customer.set_password(demo_password)
        db.add(customer)
        counts["customers"] += 1

    for row in SAMPLE_VEHICLES:
        (plate, brand, model, year, vtype, seats, transmission, fuel,
         daily, hourly, color, status, description) = row
        if db.scalars(select(Vehicle).where(Vehicle.plate_number == plate)).first():
            continue
        db.add(
            Vehicle(
                plate_number=plate,
                brand=brand,
                model=model,
                year=year,
                vehicle_type=vtype,
                seats=seats,
                transmission=transmission,
                fuel_type=fuel,
                daily_rate=Decimal(daily),
                hourly_rate=Decimal(hourly) if hourly else None,
                color=color,
                status=status,
                description=description,
            )
        )
        counts["vehicles"] += 1

    db.commit()

    # The one vehicle seeded as MAINTENANCE gets the record that explains it, so
    # the seeded state agrees with the bookability rule rather than contradicting it.
    workshop = db.scalars(select(Vehicle).where(Vehicle.status == "MAINTENANCE")).first()
    if workshop is not None and db.scalars(select(Maintenance)).first() is None:
        start = today()
        db.add(
            Maintenance(
                vehicle_id=workshop.id,
                description="Scheduled brake replacement and aircon service.",
                start_date=start - timedelta(days=2),
                expected_end_date=start + timedelta(days=5),
                status="IN_PROGRESS",
                cost=Decimal("8500.00"),
            )
        )
        counts["maintenance"] += 1
        db.commit()

    return counts


@click.command("seed")
@click.option("--password", prompt=True, hide_input=True, help="Password for the admin account.")
@click.option(
    "--demo-password",
    prompt=True,
    hide_input=True,
    help="Shared password for the three sample customers.",
)
@with_appcontext
def seed_command(password: str, demo_password: str):
    """Insert the demo fleet, accounts and fee schedule, skipping what exists."""
    counts = seed_everything(get_session(), password, demo_password)
    click.echo(
        f"Added {counts['vehicles']} vehicle(s), {counts['customers']} customer(s), "
        f"{counts['admins']} admin(s), {counts['maintenance']} maintenance record(s)."
    )


@click.command("reset-db")
@click.option("--yes", is_flag=True, help="Required to reset anything other than local SQLite.")
@click.option("--password", prompt=True, hide_input=True, help="Password for the admin account.")
@click.option(
    "--demo-password",
    prompt=True,
    hide_input=True,
    help="Shared password for the three sample customers.",
)
@with_appcontext
def reset_db_command(yes: bool, password: str, demo_password: str):
    """Drop every table, recreate them, and seed the demo data.

    This destroys data, so it refuses to touch anything but a local SQLite file
    unless --yes is passed explicitly.
    """
    url = current_app.config["DATABASE_URL"]
    # Parse the scheme rather than prefix-matching the raw string: a URL such as
    # "sqlite_evil://prodhost/db" starts with "sqlite" but is not SQLite, and
    # this is the only thing standing between a mistyped DATABASE_URL and a
    # dropped production database.
    scheme = urlparse(url).scheme.split("+", 1)[0]
    if scheme != "sqlite" and not yes:
        raise click.ClickException(
            f"Refusing to drop every table on {url.split('@')[-1]} without --yes."
        )

    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    click.echo("Tables dropped and recreated.")

    counts = seed_everything(get_session(), password, demo_password)
    click.echo(
        f"Seeded {counts['vehicles']} vehicle(s), {counts['customers']} customer(s), "
        f"{counts['maintenance']} maintenance record(s)."
    )
    click.echo("")
    click.echo("Sign in as:")
    click.echo("  admin    / the --password you just set   (Rental Management Dashboard)")
    for username, _email, full_name, _phone in SAMPLE_CUSTOMERS:
        click.echo(f"  {username:<8} / the --demo-password you just set   ({full_name})")
