"""Flask-WTF forms. Flask-WTF also gives every form CSRF protection for free."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DecimalField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    EqualTo,
    InputRequired,
    Length,
    NumberRange,
    Optional,
    Regexp,
)

from .clock import today
from .models import FUEL_TYPES, TRANSMISSIONS, VEHICLE_STATUSES, VEHICLE_TYPES

MIN_YEAR = 1950

# Deliberately loose: "something@something.tld". A stricter check would need the
# email-validator package, and the only real proof an address works is sending
# to it, which this app does not do yet.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"
MIN_PASSWORD_LENGTH = 8


def max_year() -> int:
    """Newest model year we accept: next year, since dealers sell ahead of the calendar."""
    return today().year + 1


def clean_plate(value: str | None) -> str | None:
    """Trim surrounding spaces and upper-case a plate number so ' abc 123 ' becomes 'ABC 123'."""
    if value is None:
        return None
    return value.strip().upper()


def clean_email(value: str | None) -> str | None:
    """Trim and lower-case an address so 'Me@Example.COM ' and 'me@example.com' are one account."""
    if value is None:
        return None
    return value.strip().lower()


def clean_text(value: str | None) -> str | None:
    """Trim surrounding spaces; turn an empty string into None so the column stays NULL."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


class LoginForm(FlaskForm):
    """Username and password for signing in."""

    username = StringField("Username", validators=[DataRequired(), Length(max=80)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in")


class SignupForm(FlaskForm):
    """Create a new account: username, email address and a password typed twice."""

    username = StringField(
        "Username",
        filters=[clean_text],
        validators=[
            DataRequired(message="Username is required."),
            Length(min=3, max=80, message="Username must be between 3 and 80 characters."),
            Regexp(
                r"^[A-Za-z0-9._-]+$",
                message="Username may only contain letters, numbers, dots, dashes and underscores.",
            ),
        ],
    )
    email = StringField(
        "Email",
        filters=[clean_email],
        validators=[
            DataRequired(message="Email is required."),
            Length(max=255),
            Regexp(EMAIL_PATTERN, message="Enter a valid email address."),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(message="Password is required."),
            Length(
                min=MIN_PASSWORD_LENGTH,
                message=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            ),
        ],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[
            DataRequired(message="Please retype the password."),
            EqualTo("password", message="The two passwords do not match."),
        ],
    )
    full_name = StringField(
        "Full name", filters=[clean_text], validators=[Optional(), Length(max=120)]
    )
    phone = StringField(
        "Phone", filters=[clean_text], validators=[Optional(), Length(max=30)]
    )
    submit = SubmitField("Create account")


class VehicleForm(FlaskForm):
    """Add / edit form for a vehicle. The same validation rules apply to both pages."""

    plate_number = StringField(
        "Plate number",
        filters=[clean_plate],
        validators=[DataRequired(message="Plate number is required."), Length(max=20)],
    )
    brand = StringField(
        "Brand",
        filters=[clean_text],
        validators=[DataRequired(message="Brand is required."), Length(max=50)],
    )
    model = StringField(
        "Model",
        filters=[clean_text],
        validators=[DataRequired(message="Model is required."), Length(max=50)],
    )
    year = IntegerField("Year", validators=[DataRequired(message="Year is required.")])
    vehicle_type = SelectField(
        "Type",
        choices=[(t, t) for t in VEHICLE_TYPES],
        validators=[DataRequired()],
    )
    color = StringField("Color", filters=[clean_text], validators=[Optional(), Length(max=30)])
    status = SelectField(
        "Status",
        choices=[(s, s.title()) for s in VEHICLE_STATUSES],
        validators=[DataRequired()],
    )
    seats = IntegerField(
        "Seats",
        validators=[
            DataRequired(message="Number of seats is required."),
            NumberRange(min=1, max=30, message="Seats must be between 1 and 30."),
        ],
    )
    transmission = SelectField(
        "Transmission", choices=[(t, t) for t in TRANSMISSIONS], validators=[DataRequired()]
    )
    fuel_type = SelectField(
        "Fuel type", choices=[(f, f) for f in FUEL_TYPES], validators=[DataRequired()]
    )
    daily_rate = DecimalField(
        "Daily rate (PHP)",
        places=2,
        validators=[
            InputRequired(message="Daily rate is required."),
            NumberRange(min=0, message="Daily rate cannot be negative."),
        ],
    )
    hourly_rate = DecimalField(
        "Hourly rate (PHP)",
        places=2,
        validators=[Optional(), NumberRange(min=0, message="Hourly rate cannot be negative.")],
    )
    image_url = StringField(
        "Image URL", filters=[clean_text], validators=[Optional(), Length(max=500)]
    )
    date_acquired = DateField("Date acquired", validators=[Optional()])
    description = TextAreaField("Description", filters=[clean_text], validators=[Optional()])
    submit = SubmitField("Save vehicle")

    def __init__(self, *args, **kwargs):
        """Set the year range here so the upper bound follows the real calendar year."""
        super().__init__(*args, **kwargs)
        self.year.validators = [
            DataRequired(message="Year is required."),
            NumberRange(
                min=MIN_YEAR,
                max=max_year(),
                message=f"Year must be between {MIN_YEAR} and {max_year()}.",
            ),
        ]


class DeleteForm(FlaskForm):
    """Empty form used only to carry a CSRF token on the delete confirmation page."""

    submit = SubmitField("Yes, delete it")


class ForgotPasswordForm(FlaskForm):
    """Ask the office to reset a password. No email is sent; an admin services it."""

    email = StringField(
        "Email",
        filters=[clean_email],
        validators=[
            DataRequired(message="Email is required."),
            Regexp(EMAIL_PATTERN, message="Enter a valid email address."),
        ],
    )
    submit = SubmitField("Request a reset")


class ChangePasswordForm(FlaskForm):
    """Change your own password, proving you know the current one."""

    current_password = PasswordField(
        "Current password", validators=[DataRequired(message="Enter your current password.")]
    )
    password = PasswordField(
        "New password",
        validators=[
            DataRequired(message="A new password is required."),
            Length(
                min=MIN_PASSWORD_LENGTH,
                message=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            ),
        ],
    )
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[
            DataRequired(message="Please retype the new password."),
            EqualTo("password", message="The two passwords do not match."),
        ],
    )
    submit = SubmitField("Change password")


class ProfileForm(FlaskForm):
    """A customer's own contact details. Username and role are not editable here."""

    full_name = StringField(
        "Full name", validators=[DataRequired(), Length(max=120)]
    )
    email = StringField(
        "Email",
        validators=[
            DataRequired(),
            Length(max=120),
            Regexp(EMAIL_PATTERN, message="Enter a valid email address."),
        ],
    )
    phone = StringField("Phone", validators=[Optional(), Length(max=30)])
    submit = SubmitField("Save changes")


class RentalRatesForm(FlaskForm):
    """The system-wide fee schedule. Nothing in a template hardcodes these."""

    # InputRequired rather than DataRequired: zero is a legitimate fee, and
    # DataRequired would reject it as missing.
    additional_driver_fee_per_day = DecimalField(
        "Additional driver, per day (PHP)",
        places=2,
        validators=[InputRequired(), NumberRange(min=0, message="A fee cannot be negative.")],
    )
    insurance_fee_per_day = DecimalField(
        "Insurance, per day (PHP)",
        places=2,
        validators=[InputRequired(), NumberRange(min=0, message="A fee cannot be negative.")],
    )
    late_fee_per_day = DecimalField(
        "Late return, per day (PHP)",
        places=2,
        validators=[InputRequired(), NumberRange(min=0, message="A fee cannot be negative.")],
    )
    submit = SubmitField("Save rates")
