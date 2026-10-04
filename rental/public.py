"""The public storefront: anyone may reach these pages, signed in or not."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, abort, render_template, request
from sqlalchemy import func, select

from . import scheduling
from .admin.fleet import GRID_PER_PAGE, paginate
from .auth import current_role
from .booking import wants
from .db import get_session
from .models import TRANSMISSIONS, VEHICLE_TYPES, RentalRates, Vehicle

bp = Blueprint("public", __name__)


@bp.route("/")
def landing():
    """The storefront's front door: the pitch, the feature cards, three vehicles.

    The featured vehicles are real rows rather than decoration, so the page is
    never selling something the fleet does not have.
    """
    db = get_session()
    featured = db.scalars(
        select(Vehicle)
        .where(Vehicle.is_active.is_(True))
        .where(Vehicle.status == "AVAILABLE")
        .order_by(Vehicle.daily_rate.asc())
        .limit(3)
    ).all()
    available_count = (
        db.scalar(
            select(func.count())
            .select_from(Vehicle)
            .where(Vehicle.is_active.is_(True))
            .where(Vehicle.status == "AVAILABLE")
        )
        or 0
    )

    return render_template(
        "storefront/landing.html", featured=featured, available_count=available_count
    )


@bp.route("/vehicles")
def browse():
    """The storefront grid: every active vehicle, narrowed by the filter form.

    Filters are plain GET parameters so a filtered grid can be bookmarked and
    shared. Date-based availability filtering arrives with the booking engine in
    phase 3; these filters are the ones that depend only on the vehicle itself.
    """
    db = get_session()
    vehicle_type = request.args.get("type", "")
    transmission = request.args.get("transmission", "")
    seats = request.args.get("seats", type=int)
    min_rate = request.args.get("min_rate", type=float)
    max_rate = request.args.get("max_rate", type=float)
    page = request.args.get("page", 1, type=int)

    query = select(Vehicle).where(Vehicle.is_active.is_(True))
    if vehicle_type in VEHICLE_TYPES:
        query = query.where(Vehicle.vehicle_type == vehicle_type)
    if transmission in TRANSMISSIONS:
        query = query.where(Vehicle.transmission == transmission)
    if seats:
        query = query.where(Vehicle.seats >= seats)
    if min_rate is not None:
        query = query.where(Vehicle.daily_rate >= Decimal(str(min_rate)))
    if max_rate is not None:
        query = query.where(Vehicle.daily_rate <= Decimal(str(max_rate)))

    query = query.order_by(Vehicle.daily_rate.asc(), Vehicle.brand.asc())
    vehicles, page, total_pages, total = paginate(query, page, GRID_PER_PAGE)

    pickup = request.args.get("pickup", "")
    return_ = request.args.get("return", "")
    interval = scheduling.parse_window(pickup, return_)
    driver = wants("driver")
    insurance = wants("insurance")

    # Only the page's own vehicles are checked -- a verdict per row on the
    # whole fleet would be a query per vehicle for rows nobody is looking at.
    verdicts = (
        {v.id: scheduling.availability_for(db, v, interval) for v in vehicles}
        if interval is not None
        else {}
    )

    return render_template(
        "storefront/browse.html",
        vehicles=vehicles,
        total=total,
        page=page,
        total_pages=total_pages,
        vehicle_type=vehicle_type,
        transmission=transmission,
        seats=seats,
        min_rate=min_rate,
        max_rate=max_rate,
        pickup=pickup,
        return_=return_,
        driver=driver,
        insurance=insurance,
        verdicts=verdicts,
        filtered=bool(
            vehicle_type or transmission or seats or min_rate or max_rate
            or pickup or return_
        ),
    )


@bp.route("/vehicles/<int:vehicle_id>")
def vehicle_detail(vehicle_id: int):
    """One vehicle's public page.

    A disabled vehicle is 404 for a visitor -- it is not part of the fleet on
    offer -- but stays reachable for an admin, who follows this link from the
    console to see what a customer would see.
    """
    db = get_session()
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        abort(404)
    if not vehicle.is_active and current_role() != "admin":
        abort(404)

    pickup = request.args.get("pickup", "")
    return_ = request.args.get("return", "")
    interval = scheduling.parse_window(pickup, return_)
    driver = wants("driver")
    insurance = wants("insurance")

    verdict = None
    quote = None
    if interval is not None:
        verdict = scheduling.availability_for(db, vehicle, interval)
        if verdict.ok:
            quote = scheduling.quote_for(
                db,
                vehicle,
                interval,
                want_additional_driver=driver,
                want_insurance=insurance,
            )

    return render_template(
        "storefront/vehicle_detail.html",
        vehicle=vehicle,
        rates=RentalRates.current(db),
        pickup=pickup,
        return_=return_,
        driver=driver,
        insurance=insurance,
        verdict=verdict,
        quote=quote,
    )
