"""Validation and private storage for driver's-license images."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from flask import current_app
from werkzeug.datastructures import FileStorage

MAX_LICENSE_BYTES = 4 * 1024 * 1024


class LicenseUploadError(ValueError):
    pass


@dataclass(frozen=True)
class LicenseImage:
    data: bytes
    content_type: str
    extension: str
    original_name: str


def validate_license_image(upload: FileStorage | None) -> LicenseImage:
    if upload is None or not upload.filename:
        raise LicenseUploadError("A photo of the driver's license is required.")
    data = upload.stream.read(MAX_LICENSE_BYTES + 1)
    if not data:
        raise LicenseUploadError("The driver's-license image is empty.")
    if len(data) > MAX_LICENSE_BYTES:
        raise LicenseUploadError("The driver's-license image must be 4 MB or smaller.")

    detected = None
    if data.startswith(b"\xff\xd8\xff"):
        detected = ("image/jpeg", ".jpg")
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = ("image/png", ".png")
    elif len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        detected = ("image/webp", ".webp")
    if detected is None:
        raise LicenseUploadError("Upload a valid JPG, PNG, or WebP image.")
    if upload.mimetype not in {detected[0], "application/octet-stream"}:
        raise LicenseUploadError("The file type does not match the uploaded image.")
    return LicenseImage(data, detected[0], detected[1], Path(upload.filename).name[:255])


def put_license(image: LicenseImage, reservation_id: int) -> str:
    """Store an image privately and return its opaque Blob URL/path."""
    pathname = f"driver-licenses/{reservation_id}/{uuid4().hex}{image.extension}"
    if current_app.testing:
        current_app.extensions.setdefault("test_license_blobs", {})[pathname] = image.data
        return pathname
    try:
        from vercel.blob import BlobClient

        blob = BlobClient().put(
            pathname,
            image.data,
            access="private",
            content_type=image.content_type,
            add_random_suffix=False,
        )
        return blob.url
    except Exception as error:
        current_app.logger.exception("Private driver's-license upload failed")
        raise LicenseUploadError(
            "Document storage is temporarily unavailable. Please try again."
        ) from error


def get_license(reference: str):
    """Return an iterable of private bytes; callers must authorize first."""
    if current_app.testing:
        data = current_app.extensions.get("test_license_blobs", {}).get(reference)
        return [data] if data is not None else None
    from vercel.blob import BlobClient

    result = BlobClient().get(reference, access="private")
    if result is None or result.status_code != 200:
        return None
    return result.stream
