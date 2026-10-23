from django import forms


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs["class"] = (
                    "form-select" if isinstance(field.widget, forms.Select) else "form-control"
                )


class ReasonForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), max_length=2000)


class ConfirmForm(forms.Form):
    pass
