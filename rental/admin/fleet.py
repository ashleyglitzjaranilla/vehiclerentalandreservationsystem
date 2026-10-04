"""The admin fleet pages: create, read, update, delete and search."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..auth import admin_required
from ..db import get_session
from ..forms import DeleteForm, VehicleForm
from ..models import VEHICLE_STATUSES, VEHICLE_TYPES, Vehicle

bp = Blueprint("admin_fleet", __name__, url_prefix="/admin/vehicles")

# The admin table shows 10 rows a page; the storefront grid shows 12 cards.
PER_PAGE = 10
GRID_PER_PAGE = 12

# Only these columns may be sorted on. Mapping the query-string value to a real
# column here means a user cannot put arbitrary SQL in the ?sort= parameter.
SORTABLE_COLUMNS = {
    "plate": Vehicle.plate_number,
    "brand": Vehicle.brand,
    "year": Vehicle.year,
    "rate": Vehicle.daily_rate,
}


def get_vehicle_or_404(vehicle_id: int) -> Vehicle:
    """Return the vehicle with this id, or raise a 404 when it does not exist."""
    vehicle = get_session().get(Vehicle, vehicle_id)
    if vehicle is None:
        abort(404)
    return vehicle


def plate_already_used(plate_number: str, ignore_id: int | None = None) -> bool:
    """Return True when another vehicle already has this plate number.

    ``ignore_id`` is the vehicle currently being edited: saving a vehicle without
    changing its plate must not collide with itself.
    """
    db = get_session()
    query = select(Vehicle.id).where(Vehicle.plate_number == plate_number)
    if ignore_id is not None:
        query = query.where(Vehicle.id != ignore_id)
    return db.scalars(query).first() is not None


def copy_form_into_vehicle(form: VehicleForm, vehicle: Vehicle) -> None:
    """Copy the validated form values onto a Vehicle object."""
    vehicle.plate_number = form.plate_number.data
    vehicle.brand = form.brand.data
    vehicle.model = form.model.data
    vehicle.year = form.year.data
    vehicle.vehicle_type = form.vehicle_type.data
    vehicle.color = form.color.data
    vehicle.status = form.status.data
    vehicle.seats = form.seats.data
    vehicle.transmission = form.transmission.data
    vehicle.fuel_type = form.fuel_type.data
    vehicle.daily_rate = form.daily_rate.data
    vehicle.hourly_rate = form.hourly_rate.data
    vehicle.image_url = form.image_url.data
    vehicle.date_acquired = form.date_acquired.data
    vehicle.description = form.description.data


def apply_sorting(query, sort: str, direction: str):
    """Add an ORDER BY clause to the query based on the ?sort= and ?dir= parameters."""
    column = SORTABLE_COLUMNS.get(sort, Vehicle.plate_number)
    return query.order_by(column.desc() if direction == "desc" else column.asc())


def paginate(query, page: int, per_page: int = PER_PAGE):
    """Run the query for one page of results and return (rows, page, total_pages, total).

    Counting and slicing are done in SQL rather than in Python, so a large table
    never has to be loaded into memory — important on a serverless host.
    """
    db = get_session()
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(page, 1), total_pages)
    rows = db.scalars(query.limit(per_page).offset((page - 1) * per_page)).all()
    return rows, page, total_pages, total


# An empty rule registers exactly "/admin/vehicles". @bp.route("/") would
# register "/admin/vehicles/", and a request for "/admin/vehicles" would then
# answer 308 rather than 200.
@bp.route("")
@admin_required
def list_vehicles():
    """List every vehicle in a table, 10 per page, sortable by plate, brand or year."""
    sort = request.args.get("sort", "plate")
    direction = request.args.get("dir", "asc")
    page = request.args.get("page", 1, type=int)

    query = apply_sorting(select(Vehicle), sort, direction)
    rows, page, total_pages, total = paginate(query, page)

    return render_template(
        "admin/vehicles_list.html",
        vehicles=rows,
        page=page,
        total_pages=total_pages,
        total=total,
        sort=sort,
        direction=direction,
    )


@bp.route("/<int:vehicle_id>")
@admin_required
def view_vehicle(vehicle_id: int):
    """Show one vehicle's full record, including the fields the table leaves out.

    ``/admin/vehicles/add`` never reaches this route because the ``int`` converter
    refuses to match the word "add".
    """
    vehicle = get_vehicle_or_404(vehicle_id)
    return render_template("admin/vehicle_detail.html", vehicle=vehicle)


@bp.route("/add", methods=["GET", "POST"])
@admin_required
def add_vehicle():
    """Show the new-vehicle form and save it when everything validates.

    The plate number is checked for duplicates before inserting so the user gets
    a friendly message on the form instead of a database error page. The
    IntegrityError branch is the safety net for the rare case where another
    request inserts the same plate in between the check and the commit.
    """
    form = VehicleForm()

    if form.validate_on_submit():
        if plate_already_used(form.plate_number.data):
            form.plate_number.errors.append(
                f"A vehicle with plate {form.plate_number.data} already exists."
            )
        else:
            db = get_session()
            vehicle = Vehicle()
            copy_form_into_vehicle(form, vehicle)
            db.add(vehicle)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                form.plate_number.errors.append("That plate number is already taken.")
            else:
                flash(f"Vehicle {vehicle.plate_number} was added.", "success")
                return redirect(url_for("admin_fleet.list_vehicles"))

    return render_template("admin/vehicle_form.html", form=form, heading="Add Vehicle", vehicle=None)


@bp.route("/<int:vehicle_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_vehicle(vehicle_id: int):
    """Show the edit form pre-filled with the vehicle's details and save the changes.

    Validation is identical to adding a vehicle; the only difference is that the
    duplicate-plate check ignores this vehicle's own row.
    """
    vehicle = get_vehicle_or_404(vehicle_id)
    form = VehicleForm(obj=vehicle)

    if form.validate_on_submit():
        if plate_already_used(form.plate_number.data, ignore_id=vehicle.id):
            form.plate_number.errors.append(
                f"Another vehicle already uses plate {form.plate_number.data}."
            )
        else:
            db = get_session()
            copy_form_into_vehicle(form, vehicle)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                form.plate_number.errors.append("That plate number is already taken.")
            else:
                flash(f"Vehicle {vehicle.plate_number} was updated.", "success")
                return redirect(url_for("admin_fleet.list_vehicles"))

    return render_template(
        "admin/vehicle_form.html", form=form, heading="Edit Vehicle", vehicle=vehicle
    )


@bp.route("/<int:vehicle_id>/delete", methods=["GET", "POST"])
@admin_required
def delete_vehicle(vehicle_id: int):
    """Ask for confirmation on GET, and actually delete the vehicle on POST.

    Deleting only on POST (with a CSRF token) means a vehicle can never be
    removed by following a link, by a crawler, or by an image tag on another
    site. The confirmation is a normal page, so no JavaScript is needed.
    """
    vehicle = get_vehicle_or_404(vehicle_id)
    form = DeleteForm()

    if form.validate_on_submit():
        db = get_session()
        plate = vehicle.plate_number
        db.delete(vehicle)
        db.commit()
        flash(f"Vehicle {plate} was deleted.", "success")
        return redirect(url_for("admin_fleet.list_vehicles"))

    return render_template("admin/vehicle_delete.html", vehicle=vehicle, form=form)


@bp.route("/<int:vehicle_id>/toggle-active", methods=["POST"])
@admin_required
def toggle_active(vehicle_id: int):
    """Disable a vehicle, or bring a disabled one back.

    A disabled vehicle keeps its history but leaves the storefront and cannot be
    booked at all, which is what requirement 16's "Disable Vehicle" means. POST
    only, so it cannot be triggered by following a link.
    """
    vehicle = get_vehicle_or_404(vehicle_id)
    vehicle.is_active = not vehicle.is_active
    get_session().commit()
    flash(
        f"Vehicle {vehicle.plate_number} was "
        f"{'re-enabled' if vehicle.is_active else 'disabled'}.",
        "success",
    )
    return redirect(url_for("admin_fleet.view_vehicle", vehicle_id=vehicle.id))


@bp.route("/search")
@admin_required
def search():
    """Search vehicles by plate, brand or model and filter by status and type.

    The text box does a case-insensitive partial match on all three text fields
    at once. ``ilike`` is used because SQLAlchemy renders it as a real ILIKE on
    Postgres and as ``lower(a) LIKE lower(b)`` on SQLite, so the same code gives
    the same results on both databases.
    """
    term = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    vehicle_type = request.args.get("type", "")
    sort = request.args.get("sort", "plate")
    direction = request.args.get("dir", "asc")
    page = request.args.get("page", 1, type=int)

    query = select(Vehicle)
    if term:
        pattern = f"%{term}%"
        query = query.where(
            Vehicle.plate_number.ilike(pattern)
            | Vehicle.brand.ilike(pattern)
            | Vehicle.model.ilike(pattern)
        )
    if status in VEHICLE_STATUSES:
        query = query.where(Vehicle.status == status)
    if vehicle_type in VEHICLE_TYPES:
        query = query.where(Vehicle.vehicle_type == vehicle_type)

    query = apply_sorting(query, sort, direction)
    rows, page, total_pages, total = paginate(query, page)

    return render_template(
        "admin/search.html",
        vehicles=rows,
        term=term,
        status=status,
        vehicle_type=vehicle_type,
        page=page,
        total_pages=total_pages,
        total=total,
        sort=sort,
        direction=direction,
        searched=bool(term or status or vehicle_type),
    )
