from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from core.models import TimestampedModel


class Semester(TimestampedModel):
    name = models.CharField(max_length=120, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-start_date", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="semester_ordered_dates",
            )
        ]

    def clean(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError("The semester end must follow its start.")

    def __str__(self):
        return self.name


class Course(TimestampedModel):
    code = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} · {self.title}"


class CourseOffering(TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        ARCHIVED = "ARCHIVED", "Archived"

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="offerings")
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, related_name="offerings")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teaching_offerings",
        limit_choices_to={"role": "TEACHER", "is_active": True},
    )
    capacity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    enrollment_start = models.DateTimeField()
    enrollment_end = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status, default=Status.DRAFT, db_index=True)

    class Meta:
        ordering = ["course__code", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["course", "semester"], name="one_course_per_semester"),
            models.CheckConstraint(
                condition=models.Q(capacity__gte=1), name="offering_positive_capacity"
            ),
            models.CheckConstraint(
                condition=models.Q(enrollment_end__gte=models.F("enrollment_start")),
                name="offering_ordered_dates",
            ),
        ]

    def clean(self):
        if (
            self.enrollment_start
            and self.enrollment_end
            and self.enrollment_start > self.enrollment_end
        ):
            raise ValidationError("Enrollment must close after it opens.")
        if self.semester_id and self.enrollment_end:
            from django.utils import timezone

            if timezone.localtime(self.enrollment_end).date() > self.semester.end_date:
                raise ValidationError("Enrollment must close before the semester ends.")
        if self.teacher_id and (self.teacher.role != "TEACHER" or not self.teacher.is_active):
            raise ValidationError("Select an active teacher.")

    @property
    def enrolled_count(self):
        return self.enrollments.filter(status="ENROLLED").count()

    @property
    def enrollment_is_open(self):
        from django.utils import timezone

        return (
            self.status == self.Status.ACTIVE
            and not self.semester.is_archived
            and not self.course.is_archived
            and self.enrollment_start <= timezone.now() <= self.enrollment_end
        )

    @property
    def available_places(self):
        return max(0, self.capacity - self.enrolled_count)

    def __str__(self):
        return f"{self.course} · {self.semester}"


class Enrollment(TimestampedModel):
    class Status(models.TextChoices):
        ENROLLED = "ENROLLED", "Enrolled"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="enrollments"
    )
    offering = models.ForeignKey(
        CourseOffering, on_delete=models.PROTECT, related_name="enrollments"
    )
    status = models.CharField(max_length=10, choices=Status, default=Status.ENROLLED, db_index=True)
    enrolled_at = models.DateTimeField()
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["student__last_name", "student__first_name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "offering"], name="one_enrollment_per_student"
            )
        ]

    def __str__(self):
        return f"{self.student} · {self.offering}"
