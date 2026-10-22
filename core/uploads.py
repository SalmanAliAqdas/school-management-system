"""Boundary for future private document workflows; no public upload route exists."""

import uuid
from pathlib import Path

from django.core.exceptions import ValidationError

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
