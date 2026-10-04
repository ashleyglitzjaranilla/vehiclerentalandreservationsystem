"""Summary reports and the CSV export."""

from __future__ import annotations

import csv
import io

from flask import Blueprint, Response, render_template
from sqlalchemy import extract, func, select

from .auth import admin_required
from .clock import now
from .db import get_session
from .models import VEHICLE_STATUSES, VEHICLE_TYPES, Vehicle

bp = Blueprint("reports", __name__, url_prefix="/admin/reports")

CSV_COLUMNS = [
    "id",
    "plate_number",
    "brand",
    "model",
    "year",
    "vehicle_type",
    "color",
    "status",
    "date_acquired",
    "description",
]


def count_by_column(column) -> dict:
    """Return {value: count} for the given column, using a single GROUP BY query."""
    rows = get_session().execute(
        select(column, func.count(Vehicle.id)).group_by(column).order_by(column)
    ).all()
    return {value: count for value, count in rows}


def count_by_year_acquired() -> list[tuple[str, int]]:
    """Return how many vehicles were acquired in each calendar year, newest first.

    Vehicles with no acquisition date are grouped together under "Not recorded".
    ``extract`` is used rather than raw SQL because SQLAlchemy translates it for
    both Postgres and SQLite.
    """
    db = get_session()
    year = extract("year", Vehicle.date_acquired)
    rows = db.execute(
        select(year, func.count(Vehicle.id))
        .where(Vehicle.date_acquired.is_not(None))
        .group_by(year)
        .order_by(year.desc())
    ).all()
    result = [(str(int(value)), count) for value, count in rows]

    missing = db.scalar(
        select(func.count(Vehicle.id)).where(Vehicle.date_acquired.is_(None))
    ) or 0
    if missing:
        result.append(("Not recorded", missing))
    return result


# An empty rule registers exactly "/admin/reports"; see admin/dashboard.py.
@bp.route("")
@admin_required
def reports():
    """Show the three summary tables: by status, by vehicle type and by year acquired."""
    db = get_session()
    total = db.scalar(select(func.count()).select_from(Vehicle)) or 0

    by_status_raw = count_by_column(Vehicle.status)
    by_type_raw = count_by_column(Vehicle.vehicle_type)

    # List every known status and type, including the ones with zero vehicles,
    # so the report has a stable shape from one run to the next.
    by_status = [(status, by_status_raw.get(status, 0)) for status in VEHICLE_STATUSES]
    by_type = [(t, by_type_raw.get(t, 0)) for t in VEHICLE_TYPES]

    return render_template(
        "admin/reports.html",
        total=total,
        by_status=by_status,
        by_type=by_type,
        by_year=count_by_year_acquired(),
        generated_at=now(),
    )


@bp.route("/export.csv")
@admin_required
def export_csv():
    """Download every vehicle as a CSV file, built with the standard library csv module.

    The file is small enough to build in memory, which suits a serverless host
    where there is no disk to write a temporary file to.
    """
    vehicles = get_session().scalars(select(Vehicle).order_by(Vehicle.plate_number)).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for vehicle in vehicles:
        writer.writerow([getattr(vehicle, column) or "" for column in CSV_COLUMNS])

    filename = f"vehicles-{now():%Y%m%d}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
