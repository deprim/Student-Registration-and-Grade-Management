from django import forms
from django.conf import settings
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
        help_texts = {
            "name": "A unique name students will recognize, for example Autumn 2026.",
            "end_date": "Enrollment for every offering in this semester must close on or "
            "before this date.",
        }


class CourseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Course
        fields = ["code", "title", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}
        help_texts = {
            "code": "A short unique code, for example CS101.",
            "description": "Shown to students in the course catalog and on the course page.",
        }


class OfferingForm(StyledFormMixin, forms.ModelForm):
    fieldsets = [
        ("Course and teacher", ["course", "semester", "teacher"]),
        ("Enrollment", ["capacity", "enrollment_start", "enrollment_end"]),
        ("Visibility", ["status"]),
    ]

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
        help_texts = {
            "course": "Choose a course from the Course library. Each course can be offered "
            "once per semester.",
            "semester": "Only current (not archived) semesters are listed.",
            "teacher": "Only active teachers are listed. The teacher sees this offering "
            "under Assigned courses and grades its students.",
            "capacity": "The maximum number of enrolled students. It cannot be lowered "
            "below the current number of enrolled students.",
            "enrollment_end": "Must be on or before the semester's end date. Teachers can "
            "publish final grades only after enrollment closes.",
            "status": "Draft offerings are hidden from students and read-only for the "
            "teacher. Choose Active to publish the offering in the course catalog.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [("DRAFT", "Draft"), ("ACTIVE", "Active")]
        self.fields["course"].queryset = Course.objects.filter(is_archived=False)
        self.fields["semester"].queryset = Semester.objects.filter(is_archived=False)
        self.fields["enrollment_start"].help_text = (
            f"Students can enroll from this date and time ({settings.TIME_ZONE} time)."
        )

    def fieldset_groups(self):
        return [(legend, [self[name] for name in names]) for legend, names in self.fieldsets]


ACADEMIC_FORMS = {
    "semesters": SemesterForm,
    "courses": CourseForm,
    "offerings": OfferingForm,
}
