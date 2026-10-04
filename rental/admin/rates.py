"""The fee schedule every rental calculation reads."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for

from ..auth import admin_required
from ..db import get_session
from ..forms import RentalRatesForm
from ..models import RentalRates

bp = Blueprint("admin_rates", __name__, url_prefix="/admin/rates")


# An empty rule registers exactly "/admin/rates"; see admin/dashboard.py.
@bp.route("", methods=["GET", "POST"])
@admin_required
def rates():
    """Show and save the one fee schedule row.

    These live in the database rather than in the templates so an admin can
    change them without a deploy (requirement 21).
    """
    db = get_session()
    current = RentalRates.current(db)
    form = RentalRatesForm(obj=current)

    if form.validate_on_submit():
        current.additional_driver_fee_per_day = form.additional_driver_fee_per_day.data
        current.insurance_fee_per_day = form.insurance_fee_per_day.data
        current.late_fee_per_day = form.late_fee_per_day.data
        db.commit()
        flash("Rental rates were updated.", "success")
        return redirect(url_for("admin_rates.rates"))

    return render_template("admin/rates.html", form=form, rates=current)
