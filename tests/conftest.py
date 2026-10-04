"""Shared pytest fixtures: a fresh in-memory SQLite database for every test."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rental import create_app
from rental.db import get_engine, get_session
from rental.models import Base, User, Vehicle

TEST_CONFIG = {
    # "sqlite://" is an in-memory database. db.create_db_engine gives it a
    # StaticPool so the whole test shares one connection.
    "DATABASE_URL": "sqlite://",
    "TESTING": True,
    "SECRET_KEY": "test-secret",
    # Turning CSRF off lets the tests post plain dictionaries. The tokens
    # themselves are Flask-WTF's job, not this project's.
    "WTF_CSRF_ENABLED": False,
}

ADMIN_PASSWORD = "secret123"
CUSTOMER_PASSWORD = "secret123"


@pytest.fixture
def app():
    """An app on an empty in-memory database holding one admin and one customer."""
    app = create_app(TEST_CONFIG)

    with app.app_context():
        Base.metadata.create_all(get_engine())
        db = get_session()

        admin = User(username="admin", email="admin@example.com", role="admin")
        admin.set_password(ADMIN_PASSWORD)

        customer = User(
            username="maria",
            email="maria@example.com",
            role="customer",
            full_name="Maria Santos",
            phone="0917 000 0001",
        )
        customer.set_password(CUSTOMER_PASSWORD)

        db.add_all([admin, customer])
        db.commit()

    yield app


@pytest.fixture
def client(app):
    """A test client with no session at all."""
    return app.test_client()


@pytest.fixture
def admin_client(app):
    """A test client signed in as the admin."""
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    return client


@pytest.fixture
def customer_client(app):
    """A test client signed in as the customer."""
    client = app.test_client()
    client.post("/login", data={"username": "maria", "password": CUSTOMER_PASSWORD})
    return client


@pytest.fixture
def sample_vehicle(app):
    """Insert one bookable vehicle and return its id."""
    with app.app_context():
        db = get_session()
        vehicle = Vehicle(
            plate_number="ABC 1234",
            brand="Toyota",
            model="Hilux",
            year=2021,
            vehicle_type="Pickup",
            color="White",
            status="AVAILABLE",
            seats=5,
            transmission="Automatic",
            fuel_type="Diesel",
            daily_rate=Decimal("2200.00"),
            date_acquired=date(2021, 3, 15),
        )
        db.add(vehicle)
        db.commit()
        return vehicle.id
