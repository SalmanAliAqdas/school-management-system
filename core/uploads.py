"""Boundary for future private document workflows; no public upload route exists."""

import uuid
import warnings
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


def private_document_path(instance, filename):
    return f"private/documents/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


def validate_pdf(upload):
    """Conservative initial gate; malware scanning is required before real deployment."""
    if Path(upload.name).suffix.lower() != ".pdf" or upload.size > MAX_DOCUMENT_BYTES:
        raise ValidationError("Upload a PDF document no larger than 2 MB.")
    position = upload.tell()
    signature = upload.read(5)
    upload.seek(position)
    if signature != b"%PDF-":
        raise ValidationError("The document does not have a valid PDF signature.")


def sanitize_image(upload):
    """Decode bounded raster input and write fresh PNG bytes without EXIF or filenames."""
    if upload.size > MAX_DOCUMENT_BYTES:
        raise ValidationError("Choose a PNG or JPEG image no larger than 2 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            upload.seek(0)
            with Image.open(upload) as source:
                if (
                    source.format not in {"PNG", "JPEG"}
                    or source.width * source.height > 16_000_000
                ):
                    raise ValidationError("Use a PNG or JPEG with at most 16 million pixels.")
                source.verify()
            upload.seek(0)
            with Image.open(upload) as source:
                frame = ImageOps.exif_transpose(source).convert("RGBA")
                frame.thumbnail((1200, 1200))
                output = BytesIO()
                frame.save(output, format="PNG")
        return ContentFile(output.getvalue(), name=f"{uuid.uuid4().hex}.png")
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValidationError("This image cannot be read. Upload a valid PNG or JPEG.") from exc
    finally:
        upload.seek(0)


@contextmanager
def image_write(instance, field):
    """Remove failed new writes and retire replaced files only after database commit."""
    previous = type(instance).objects.filter(pk=instance.pk).values_list(field, flat=True).first()
    try:
        yield
    except Exception:
        current = getattr(instance, field)
        if current and current.name != previous and current._committed:
            current.storage.delete(current.name)
        raise
    else:
        current = getattr(instance, field)
        if previous and (not current or previous != current.name):
            storage = instance._meta.get_field(field).storage
            transaction.on_commit(lambda: storage.delete(previous), robust=True)
