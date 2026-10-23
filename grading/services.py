from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from accounts.models import User
from academics.models import Enrollment
from academics.services import locked_offering, require_writable
from core.access import require_actor
from core.services import audit, snapshot
from .models import Assessment, Grade, FinalGrade


def teacher_offering(actor, offering_id):
    actor = require_actor(actor, [User.Role.TEACHER])
    offering = locked_offering(offering_id)
    if offering.teacher_id != actor.pk:
        from django.http import Http404

        raise Http404
    require_writable(offering)
    return offering


def grade_summary(enrollment, assessment_count=None):
    values = list(enrollment.grades.values_list("value", flat=True))
    count = (
        assessment_count
        if assessment_count is not None
        else enrollment.offering.assessments.count()
    )
    average = sum(map(Decimal, values), Decimal(0)) / len(values) if values else None
    final = FinalGrade.objects.filter(enrollment=enrollment, is_published=True).first()
    return {
        "average": average.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if average is not None
        else None,
        "raw_average": average,
        "proposed": int(average.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if average is not None
        else None,
        "missing": max(0, count - len(values)),
        "final": final,
    }


@transaction.atomic
def save_assessment(actor, offering_id, data, assessment_id=None, delete=False):
    offering = teacher_offering(actor, offering_id)
    if offering.enrollments.filter(final_grade__is_published=True).exists():
        raise ValidationError("Assessments are locked while final grades are published.")
    obj = (
        get_object_or_404(Assessment, pk=assessment_id, offering=offering)
        if assessment_id
        else Assessment(offering=offering)
    )
    fields = ["title", "description", "due_date", "display_order"]
    old = snapshot(obj, fields) if obj.pk else {}
    if delete:
        if obj.grades.exists():
            raise ValidationError("An assessment with grades cannot be deleted.")
        audit(actor, "Assessment deleted", obj, old=old)
        obj.delete()
        return
    for field in fields:
        setattr(obj, field, data[field])
    obj.full_clean()
    obj.save()
    audit(actor, "Assessment saved", obj, old, snapshot(obj, fields))
    return obj


@transaction.atomic
def save_grades(actor, offering_id, changes):
    offering = teacher_offering(actor, offering_id)
    for change in changes:
        enrollment = get_object_or_404(
            Enrollment, pk=change["enrollment_id"], offering=offering, status="ENROLLED"
        )
        assessment = get_object_or_404(Assessment, pk=change["assessment_id"], offering=offering)
        if FinalGrade.objects.filter(enrollment=enrollment, is_published=True).exists():
            raise ValidationError("Published final grades lock this student's grades.")
        value = change["value"]
        if type(value) is not int or not 1 <= value <= 10:
            raise ValidationError("Grades must be whole numbers from 1 to 10.")
        grade = Grade.objects.filter(enrollment=enrollment, assessment=assessment).first()
        old = snapshot(grade, ["value", "comment"]) if grade else {}
        grade = grade or Grade(enrollment=enrollment, assessment=assessment)
        grade.value, grade.comment, grade.last_editor = (
            value,
            change.get("comment", ""),
            actor,
        )
        grade.full_clean()
        grade.save()
        audit(
            actor,
            "Assessment grade saved",
            grade,
            old,
            snapshot(grade, ["value", "comment"]),
        )


@transaction.atomic
def publish_final(actor, offering_id, enrollment_id):
    offering = teacher_offering(actor, offering_id)
    if timezone.now() <= offering.enrollment_end:
        raise ValidationError("Final grades can only be published after enrollment closes.")
    enrollment = get_object_or_404(
        Enrollment, pk=enrollment_id, offering=offering, status="ENROLLED"
    )
    summary = grade_summary(enrollment)
    if not offering.assessments.exists() or summary["missing"] or summary["raw_average"] is None:
        raise ValidationError("Grade every assessment before publishing a final grade.")
    if summary["final"]:
        raise ValidationError("This final grade is already published.")
    final, _ = FinalGrade.objects.update_or_create(
        enrollment=enrollment,
        defaults={
            "average_snapshot": summary["raw_average"],
            "value": summary["proposed"],
            "publisher": actor,
            "published_at": timezone.now(),
            "is_published": True,
        },
    )
    audit(
        actor,
        "Final grade published",
        final,
        new={"value": final.value, "average": str(summary["raw_average"])},
    )
    return final


@transaction.atomic
def unpublish_final(actor, offering_id, enrollment_id, reason):
    actor = require_actor(actor, [User.Role.ADMIN])
    offering = locked_offering(offering_id)
    require_writable(offering)
    if not reason.strip():
        raise ValidationError("A reason is required to unpublish a final grade.")
    final = get_object_or_404(
        FinalGrade,
        enrollment_id=enrollment_id,
        enrollment__offering=offering,
        is_published=True,
    )
    final.is_published = False
    final.save()
    audit(
        actor,
        "Final grade unpublished",
        final,
        old={"value": final.value},
        new={"is_published": False},
        reason=reason,
    )


@transaction.atomic
def clear_grade(actor, offering_id, grade_id, reason):
    actor = require_actor(actor, [User.Role.ADMIN])
    offering = locked_offering(offering_id)
    require_writable(offering)
    grade = get_object_or_404(Grade, pk=grade_id, enrollment__offering=offering)
    if not reason.strip():
        raise ValidationError("A reason is required to clear a grade.")
    if FinalGrade.objects.filter(enrollment=grade.enrollment, is_published=True).exists():
        raise ValidationError("Unpublish the final grade before clearing an assessment grade.")
    audit(
        actor,
        "Assessment grade cleared",
        grade,
        old=snapshot(grade, ["value", "comment"]),
        reason=reason,
    )
    grade.delete()
