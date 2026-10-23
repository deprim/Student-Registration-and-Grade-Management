from django import forms
from core.forms import StyledFormMixin
from .models import Assessment


class AssessmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Assessment
        fields = ["title", "description", "due_date", "display_order"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }


class GradeCellForm(StyledFormMixin, forms.Form):
    enrollment_id = forms.IntegerField(widget=forms.HiddenInput)
    assessment_id = forms.IntegerField(widget=forms.HiddenInput)
    value = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=10,
        label="Grade",
        widget=forms.NumberInput(attrs={"placeholder": "—", "inputmode": "numeric"}),
    )
    comment = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.TextInput(attrs={"placeholder": "Comment"}),
    )

    def clean(self):
        data = super().clean()
        if data.get("value") is None:
            if self.initial.get("value") is not None:
                raise forms.ValidationError("Only an administrator can clear an existing grade.")
            if data.get("comment"):
                raise forms.ValidationError("Enter a grade before adding a comment.")
        return data
