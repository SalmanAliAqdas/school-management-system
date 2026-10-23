import io
from pathlib import Path

from django.core.exceptions import ValidationError
from PIL import Image


def read_private_upload(upload):
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError("Each attachment must be at most 5 MB.")
    data = upload.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise ValidationError("Attachment is too large.")
    extension = Path(upload.name).suffix.lower()
    types = {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    if extension not in types or upload.content_type not in (
        types.get(extension),
        "application/octet-stream",
    ):
        raise ValidationError("Use PDF, UTF-8 text, PNG or JPEG with a matching content type.")
    if extension == ".pdf" and (not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]):
        raise ValidationError("The file does not contain a recognizable PDF.")
    if extension == ".txt":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("Text attachments must be UTF-8.") from exc
        if "\x00" in text:
            raise ValidationError("Binary content is not a text document.")
    if extension in (".png", ".jpg", ".jpeg"):
        try:
            with Image.open(io.BytesIO(data)) as picture:
                picture.verify()
                if picture.format != ("PNG" if extension == ".png" else "JPEG"):
                    raise ValueError()
        except Exception as exc:
            raise ValidationError("Invalid image content.") from exc
    name = Path(upload.name.replace("\\", "/")).name
    name = "".join(c for c in name if c.isalnum() or c in " ._-")[:120] or "document" + extension
    return {"filename": name, "content_type": types[extension], "data": data}
