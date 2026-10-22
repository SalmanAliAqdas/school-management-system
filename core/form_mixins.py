from django import forms

from .uploads import sanitize_image


class PrivateImageWidget(forms.ClearableFileInput):
    template_name = "widgets/private_image.html"


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            )
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(
                    format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}
                )


class ImageFormMixin(StyledFormMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("photo", "logo"):
            if name in self.fields:
                self.fields[name].widget = PrivateImageWidget(
                    attrs={"class": "form-control", "accept": "image/png,image/jpeg"}
                )
                self.fields[
                    name
                ].help_text = "PNG or JPEG, up to 2 MB. Images are resized and metadata is removed."

    def clean(self):
        data = super().clean()
        for name in ("photo", "logo"):
            upload = self.files.get(name)
            if upload and name not in self.errors:
                try:
                    data[name] = sanitize_image(upload)
                except forms.ValidationError as exc:
                    self.add_error(name, exc)
        return data
