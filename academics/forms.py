from django import forms
from core.forms import StyledFormMixin
from .models import Semester, Course, CourseOffering


class SemesterForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Semester
        fields = ["name", "start_date", "end_date"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class CourseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Course
        fields = ["code", "title", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class OfferingForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CourseOffering
        fields = [
            "course",
            "semester",
            "teacher",
            "capacity",
            "enrollment_start",
            "enrollment_end",
            "status",
        ]
        widgets = {
            "enrollment_start": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}
            ),
            "enrollment_end": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [("DRAFT", "Draft"), ("ACTIVE", "Active")]
        self.fields["course"].queryset = Course.objects.filter(is_archived=False)
        self.fields["semester"].queryset = Semester.objects.filter(is_archived=False)


ACADEMIC_FORMS = {
    "semesters": SemesterForm,
    "courses": CourseForm,
    "offerings": OfferingForm,
}
