"""SQLAlchemy models: the login accounts and the vehicles being tracked."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from werkzeug.security import check_password_hash, generate_password_hash

from .clock import now

# The fixed option lists used by the forms, the filters and the reports.
VEHICLE_TYPES = ["Sedan", "Hatchback", "MPV", "SUV", "Pickup", "Van", "Truck", "Motorcycle"]
TRANSMISSIONS = ["Automatic", "Manual"]
FUEL_TYPES = ["Gasoline", "Diesel", "Electric", "Hybrid"]

# A vehicle's state right now. Whether it can be booked for a particular date
# range is computed from overlapping reservations, rentals and maintenance --
# never read off this column. See the spec's "Vehicle status is not the same
# thing as availability".
VEHICLE_STATUSES = ["AVAILABLE", "RESERVED", "RENTED", "MAINTENANCE"]

STATUS_BADGES = {
    "AVAILABLE": "pill-green",
    "RESERVED": "pill-amber",
    "RENTED": "pill-blue",
    "MAINTENANCE": "pill-slate",
}


class Base(DeclarativeBase):
    """Base class every model inherits from."""


ROLES = ["admin", "customer"]


class User(Base):
    """A person who can log in: either the admin running the fleet or a customer renting from it."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="customer")
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Set by the forgot-password page. An admin services it by issuing a
    # temporary password; there is no email sending in this project.
    reset_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    def set_password(self, password: str) -> None:
        """Hash the given plain-text password and store it. The password itself is never saved."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Return True when the plain-text password matches the stored hash."""
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def display_name(self) -> str:
        """The name to greet this person by, falling back to their username."""
        return self.full_name or self.username

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class Vehicle(Base):
    """One vehicle in the fleet."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    brand: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(20), nullable=False)
    color: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="AVAILABLE")
    seats: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    transmission: Mapped[str] = mapped_column(String(20), nullable=False, default="Automatic")
    fuel_type: Mapped[str] = mapped_column(String(20), nullable=False, default="Gasoline")
    daily_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # NULL means this vehicle is daily-only: a part day rounds up to a whole one.
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # An absolute URL or a path under static/. Blank falls back to the per-type
    # silhouette, so a vehicle never renders a broken image.
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # False is what "Disable Vehicle" does: hidden from the storefront and
    # unbookable, but its history is kept.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    date_acquired: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, onupdate=now, nullable=False
    )

    @property
    def badge_class(self) -> str:
        """Return the status pill colour class that matches this vehicle's status."""
        return STATUS_BADGES.get(self.status, "pill-slate")

    @property
    def display_name(self) -> str:
        """The vehicle as a customer sees it named, e.g. 'Toyota Vios 2024'."""
        return f"{self.brand} {self.model} {self.year}"

    @property
    def type_slug(self) -> str:
        """The vehicle type lower-cased, which is the silhouette's filename."""
        return (self.vehicle_type or "sedan").lower()

    def __repr__(self) -> str:
        return f"<Vehicle {self.plate_number} {self.brand} {self.model}>"


# The fees a rental can attract, on top of the vehicle's own daily rate. These
# live in the database rather than in the templates so an admin can change them
# (requirement 21) without a deploy.
DEFAULT_ADDITIONAL_DRIVER_FEE = Decimal("500.00")
DEFAULT_INSURANCE_FEE = Decimal("300.00")
DEFAULT_LATE_FEE = Decimal("800.00")


class RentalRates(Base):
    """The system-wide fee schedule. Exactly one row, id 1."""

    __tablename__ = "rental_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    additional_driver_fee_per_day: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=DEFAULT_ADDITIONAL_DRIVER_FEE
    )
    insurance_fee_per_day: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=DEFAULT_INSURANCE_FEE
    )
    late_fee_per_day: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=DEFAULT_LATE_FEE
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, onupdate=now, nullable=False
    )

    @classmethod
    def current(cls, session) -> "RentalRates":
        """Return the one rates row, creating it with the defaults if it is missing.

        Every caller gets a row, so no page has to handle the table being empty
        -- which it is on a database created by ``init-db`` without a seed.
        """
        rates = session.get(cls, 1)
        if rates is None:
            rates = cls(id=1)
            session.add(rates)
            session.commit()
        return rates


RESERVATION_STATUSES = ["PENDING", "CONFIRMED", "CANCELLED", "COMPLETED", "REJECTED"]
RENTAL_STATUSES = ["ACTIVE", "COMPLETED"]
MAINTENANCE_STATUSES = ["SCHEDULED", "IN_PROGRESS", "COMPLETED"]

RESERVATION_BADGES = {
    "PENDING": "pill-amber",
    "CONFIRMED": "pill-green",
    "CANCELLED": "pill-slate",
    "COMPLETED": "pill-blue",
    "REJECTED": "pill-red",
}

RENTAL_BADGES = {
    "ACTIVE": "pill-blue",
    "COMPLETED": "pill-green",
}


class Reservation(Base):
    """A customer's request to rent one vehicle over one date range."""

    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reservation_number: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)

    # One datetime per endpoint rather than a separate date and time column:
    # overlap comparison is the most important query in the system and it needs
    # a single comparable value. Forms still collect date and time separately.
    pickup_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    return_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    pickup_location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    return_location: Mapped[str | None] = mapped_column(String(120), nullable=True)

    want_additional_driver: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    want_insurance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    rental_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rental_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # The rates are snapshotted here on purpose. An admin editing the vehicle's
    # daily rate afterwards must not change what this customer was quoted.
    daily_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    base_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    additional_fees: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, onupdate=now, nullable=False
    )

    def assign_number(self) -> None:
        """Set the human-facing reference from the row id, e.g. RES-00001.

        Called after the insert has been flushed and inside the same
        transaction, so the id exists and two concurrent requests cannot be
        handed the same number.
        """
        self.reservation_number = f"RES-{self.id:05d}"

    @property
    def badge_class(self) -> str:
        return RESERVATION_BADGES.get(self.status, "pill-slate")

    def __repr__(self) -> str:
        return f"<Reservation {self.reservation_number} {self.status}>"


class Rental(Base):
    """A confirmed reservation that has actually been picked up."""

    __tablename__ = "rentals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rental_number: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("reservations.id"), unique=True, nullable=False
    )
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    # Denormalised so the reports can group without joining through reservations.
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    actual_pickup: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expected_return: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    actual_return: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    rental_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rental_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    late_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    base_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    late_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    additional_fees: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now, onupdate=now, nullable=False
    )

    def assign_number(self) -> None:
        """Set the human-facing reference from the row id, e.g. RNT-00042."""
        self.rental_number = f"RNT-{self.id:05d}"

    @property
    def badge_class(self) -> str:
        return RENTAL_BADGES.get(self.status, "pill-slate")

    def __repr__(self) -> str:
        return f"<Rental {self.rental_number} {self.status}>"


class Maintenance(Base):
    """A window during which a vehicle is off the road."""

    __tablename__ = "maintenance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SCHEDULED")
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    @property
    def blocks_booking(self) -> bool:
        """True while this window still takes the vehicle off the road.

        A completed record is history and blocks nothing; a scheduled future one
        blocks its dates, which is what stops a customer booking over it.
        """
        return self.status != "COMPLETED"

    def __repr__(self) -> str:
        return f"<Maintenance vehicle={self.vehicle_id} {self.status}>"
