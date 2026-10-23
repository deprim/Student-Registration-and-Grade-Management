from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from core.models import TimestampedModel


class Assessment(TimestampedModel):
    offering = models.ForeignKey(
        "academics.CourseOffering", on_delete=models.PROTECT, related_name="assessments"
    )
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "pk"]

    def __str__(self):
        return self.title


class Grade(TimestampedModel):
    enrollment = models.ForeignKey(
        "academics.Enrollment", on_delete=models.PROTECT, related_name="grades"
    )
    assessment = models.ForeignKey(Assessment, on_delete=models.PROTECT, related_name="grades")
    value = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    comment = models.TextField(blank=True)
    last_editor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "assessment"], name="one_grade_per_assessment"
            ),
            models.CheckConstraint(
                condition=models.Q(value__gte=1, value__lte=10),
                name="grade_value_range",
            ),
        ]

    def clean(self):
        if (
            self.enrollment_id
            and self.assessment_id
            and self.enrollment.offering_id != self.assessment.offering_id
        ):
            raise ValidationError("The student and assessment must belong to the same offering.")


class FinalGrade(TimestampedModel):
    enrollment = models.OneToOneField(
        "academics.Enrollment", on_delete=models.PROTECT, related_name="final_grade"
    )
    average_snapshot = models.DecimalField(max_digits=8, decimal_places=5)
    value = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    publisher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    published_at = models.DateTimeField()
    is_published = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(value__gte=1, value__lte=10),
                name="final_grade_value_range",
            )
        ]
