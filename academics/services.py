from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from accounts.models import User
from core.access import require_actor
from core.services import audit, snapshot
from .models import Semester, Course, CourseOffering, Enrollment


def locked_offering(offering_id):
    """Lock parent then child consistently with semester archiving."""
    semester_id = CourseOffering.objects.values_list("semester_id", flat=True).get(pk=offering_id)
    semester = Semester.objects.select_for_update().get(pk=semester_id)
    offering = CourseOffering.objects.select_for_update().get(pk=offering_id)
    offering.semester = semester
    return offering


def require_writable(offering):
    if offering.status != CourseOffering.Status.ACTIVE or offering.semester.is_archived:
        raise ValidationError("This offering is not active or is archived.")


def require_enrollment_window(offering):
    require_writable(offering)
    now = timezone.now()
    if not offering.enrollment_start <= now <= offering.enrollment_end:
        raise ValidationError("Enrollment is not currently open.")


@transaction.atomic
def enroll(actor, offering_id):
    actor = require_actor(actor, [User.Role.STUDENT])
    offering = locked_offering(offering_id)
    require_enrollment_window(offering)
    enrollment = Enrollment.objects.filter(student=actor, offering=offering).first()
    if enrollment and enrollment.status == Enrollment.Status.ENROLLED:
        raise ValidationError("You are already enrolled in this course.")
    if offering.enrolled_count >= offering.capacity:
        raise ValidationError("This course is full.")
    if enrollment:
        enrollment.status = Enrollment.Status.ENROLLED
        enrollment.enrolled_at = timezone.now()
        enrollment.withdrawn_at = None
        enrollment.save()
    else:
        enrollment = Enrollment.objects.create(
            student=actor, offering=offering, enrolled_at=timezone.now()
        )
    audit(actor, "Student enrolled", enrollment, new={"status": enrollment.status})
    return enrollment


@transaction.atomic
def withdraw(actor, offering_id):
    actor = require_actor(actor, [User.Role.STUDENT])
    offering = locked_offering(offering_id)
    require_enrollment_window(offering)
    enrollment = Enrollment.objects.get(
        student=actor, offering=offering, status=Enrollment.Status.ENROLLED
    )
    if enrollment.grades.exists() or hasattr(enrollment, "final_grade"):
        raise ValidationError("You cannot withdraw after grades have been recorded.")
    enrollment.status = Enrollment.Status.WITHDRAWN
    enrollment.withdrawn_at = timezone.now()
    enrollment.save()
    audit(actor, "Student withdrew", enrollment, new={"status": enrollment.status})


ACADEMIC_MODELS = {
    "semesters": Semester,
    "courses": Course,
    "offerings": CourseOffering,
}
ACADEMIC_FIELDS = {
    "semesters": ["name", "start_date", "end_date"],
    "courses": ["code", "title", "description"],
    "offerings": [
        "course",
        "semester",
        "teacher",
        "capacity",
        "enrollment_start",
        "enrollment_end",
        "status",
    ],
}


@transaction.atomic
def save_academic(actor, kind, data, pk=None):
    actor = require_actor(actor, [User.Role.ADMIN])
    model = ACADEMIC_MODELS[kind]
    if kind == "offerings":
        target_course = Course.objects.select_for_update().get(pk=data["course"].pk)
        semester_ids = {data["semester"].pk}
        if pk:
            semester_ids.add(
                CourseOffering.objects.values_list("semester_id", flat=True).get(pk=pk)
            )
        semesters = {
            semester.pk: semester
            for semester in Semester.objects.select_for_update()
            .filter(pk__in=semester_ids)
            .order_by("pk")
        }
        obj = CourseOffering.objects.select_for_update().get(pk=pk) if pk else model()
        if pk:
            if obj.semester_id not in semesters:
                raise ValidationError("This offering changed. Refresh the page before editing.")
            obj.semester = semesters[obj.semester_id]
        target_semester = semesters[data["semester"].pk]
        data = {
            **data,
            "course": target_course,
            "semester": target_semester,
            "teacher": User.objects.get(pk=data["teacher"].pk),
        }
        if target_semester.is_archived or target_course.is_archived:
            raise ValidationError("Archived courses and semesters cannot be used.")
        if pk:
            if obj.status == "ARCHIVED" or obj.semester.is_archived:
                raise ValidationError("Archived offerings are read-only.")
            if obj.enrollments.filter(final_grade__is_published=True).exists():
                raise ValidationError("Unpublish all final grades before editing this offering.")
            if obj.enrollments.exists() or obj.assessments.exists():
                if obj.course_id != data["course"].pk or obj.semester_id != data["semester"].pk:
                    raise ValidationError(
                        "An offering with academic history cannot change course or semester."
                    )
                if obj.status == "ACTIVE" and data["status"] == "DRAFT":
                    raise ValidationError(
                        "An offering with academic history cannot return to draft."
                    )
            if data["capacity"] < obj.enrolled_count:
                raise ValidationError("Capacity cannot be lower than current enrollment.")
    else:
        obj = model.objects.select_for_update().get(pk=pk) if pk else model()
        if obj.is_archived:
            raise ValidationError("Archived records are read-only.")
        if kind == "semesters" and pk:
            for offering in obj.offerings.all():
                if timezone.localtime(offering.enrollment_end).date() > data["end_date"]:
                    raise ValidationError(
                        "The semester cannot end before an offering's enrollment closes."
                    )
    old = snapshot(obj, ACADEMIC_FIELDS[kind]) if pk else {}
    for field in ACADEMIC_FIELDS[kind]:
        setattr(obj, field, data[field])
    if kind == "offerings" and obj.status not in ["DRAFT", "ACTIVE"]:
        raise ValidationError("Use the archive action to archive an offering.")
    obj.full_clean()
    obj.save()
    audit(actor, "Academic record saved", obj, old, snapshot(obj, ACADEMIC_FIELDS[kind]))
    return obj


@transaction.atomic
def archive_academic(actor, kind, pk):
    actor = require_actor(actor, [User.Role.ADMIN])
    obj = (
        locked_offering(pk)
        if kind == "offerings"
        else ACADEMIC_MODELS[kind].objects.select_for_update().get(pk=pk)
    )
    if kind == "offerings":
        require_writable(obj)
        if timezone.now() <= obj.enrollment_end:
            raise ValidationError("Wait until enrollment closes before archiving.")
        if (
            obj.enrollments.filter(status="ENROLLED")
            .exclude(final_grade__is_published=True)
            .exists()
        ):
            raise ValidationError(
                "Publish final grades for every enrolled student before archiving."
            )
        obj.status = "ARCHIVED"
    else:
        list(obj.offerings.select_for_update().values_list("pk", flat=True))
        if obj.offerings.exclude(status="ARCHIVED").exists():
            raise ValidationError("Archive all related offerings first.")
        obj.is_archived = True
    obj.save()
    audit(actor, "Academic record archived", obj, new={"archived": True})
