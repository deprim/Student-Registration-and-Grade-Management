from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.forms import formset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from academics.models import Enrollment
from core.access import role_required, staff_offering
from core.ui import paginate, confirmation, form_errors, enrollment_window
from .forms import AssessmentForm, GradeCellForm
from .models import Assessment, Grade
from .services import (
    grade_summary,
    save_grades,
    save_assessment,
    publish_final,
    unpublish_final,
    clear_grade,
)


def gradebook_url(request, pk):
    return reverse(
        "management:gradebook" if request.user.role == "ADMIN" else "teacher:gradebook",
        args=[pk],
    )


def publish_state(summary, has_assessments, enrollment_closed, window):
    """Explain whether a final can be published. publish_final still enforces the rules."""
    if summary["final"]:
        return {"can_publish": False, "reasons": []}
    reasons = []
    if not has_assessments:
        reasons.append("Add at least one assessment first.")
    elif summary["missing"]:
        count = summary["missing"]
        reasons.append(f"{count} grade{'' if count == 1 else 's'} not yet entered.")
    if not enrollment_closed:
        reasons.append(f"Available after enrollment closes on {window['closes']}.")
    return {"can_publish": not reasons, "reasons": reasons}


def read_only_reason(user, offering):
    if user.role == "ADMIN":
        return (
            "Administrators can review grades here. Only the assigned teacher can enter "
            "grades or publish final grades."
        )
    if offering.status == "DRAFT":
        return (
            "This offering is still a draft. An administrator must set it to Active before "
            "you can add assessments or enter grades."
        )
    return "This offering is archived. Its grades and final grades are permanently read-only."


@role_required("ADMIN", "TEACHER")
def gradebook(request, pk):
    offering = staff_offering(request.user, pk)
    editable = (
        request.user.role == "TEACHER"
        and offering.status == "ACTIVE"
        and not offering.semester.is_archived
    )
    if request.method == "POST" and not editable:
        raise PermissionDenied
    window = enrollment_window(offering)
    enrollment_closed = timezone.now() > offering.enrollment_end
    assessments_locked = offering.enrollments.filter(final_grade__is_published=True).exists()
    assessments = list(offering.assessments.all())
    page = paginate(
        request,
        offering.enrollments.filter(status="ENROLLED").select_related(
            "student", "student__student_profile"
        ),
    )
    grades = {
        (g.enrollment_id, g.assessment_id): g
        for g in Grade.objects.filter(enrollment__in=page.object_list)
    }
    initial, rows = [], []
    for enrollment in page:
        summary = grade_summary(enrollment, len(assessments))
        cells = []
        for assessment in assessments:
            grade = grades.get((enrollment.pk, assessment.pk))
            initial.append(
                {
                    "enrollment_id": enrollment.pk,
                    "assessment_id": assessment.pk,
                    "value": grade.value if grade else None,
                    "comment": grade.comment if grade else "",
                }
            )
            cells.append(
                {
                    "grade": grade,
                    "assessment": assessment,
                    "form_index": len(initial) - 1,
                }
            )
        rows.append(
            {
                "enrollment": enrollment,
                "summary": summary,
                "cells": cells,
                "publish": publish_state(summary, bool(assessments), enrollment_closed, window),
            }
        )
    formset = formset_factory(GradeCellForm, extra=0, max_num=5000, absolute_max=5000)(
        request.POST if request.method == "POST" else None, initial=initial
    )
    for row in rows:
        for cell in row["cells"]:
            index = cell["form_index"]
            cell["form"] = formset.forms[index] if index < len(formset.forms) else None
            if cell["form"] and (not editable or row["summary"]["final"]):
                for field in cell["form"].fields.values():
                    field.disabled = True
    if request.method == "POST" and formset.is_valid():
        try:
            changes = [
                form.cleaned_data
                for form in formset
                if form.has_changed() and form.cleaned_data.get("value") is not None
            ]
            save_grades(request.user, pk, changes)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Grades saved. Students can see them now.")
            return redirect(
                gradebook_url(request, pk) + (f"?page={page.number}" if page.number > 1 else "")
            )
    return render(
        request,
        "grading/gradebook.html",
        {
            "offering": offering,
            "assessments": assessments,
            "rows": rows,
            "formset": formset,
            "editable": editable,
            "page_obj": page,
            "window": window,
            "enrollment_closed": enrollment_closed,
            "assessments_locked": assessments_locked,
            "can_manage_assessments": editable and not assessments_locked,
            "read_only_reason": "" if editable else read_only_reason(request.user, offering),
        },
    )


@role_required("ADMIN")
def management_gradebook(request, pk):
    return gradebook(request, pk)


@role_required("TEACHER")
def teacher_gradebook(request, pk):
    return gradebook(request, pk)


@role_required("TEACHER")
def assessment_edit(request, pk, assessment_id=None):
    offering = staff_offering(request.user, pk)
    assessment = (
        get_object_or_404(Assessment, pk=assessment_id, offering=offering)
        if assessment_id
        else None
    )
    form = AssessmentForm(request.POST if request.method == "POST" else None, instance=assessment)
    if request.method == "POST" and form.is_valid():
        try:
            save_assessment(request.user, pk, form.cleaned_data, assessment_id)
        except ValidationError as error:
            form_errors(form, error)
        else:
            messages.success(request, f"Assessment {form.cleaned_data['title']} saved.")
            return redirect("teacher:gradebook", pk=pk)
    return render(
        request,
        "core/form.html",
        {
            "title": "Edit assessment" if assessment_id else "Add assessment",
            "description": f"{offering.course.title}. Grades are whole numbers from 1 to 10, "
            "and all assessments count equally towards the final grade.",
            "form": form,
            "back_url": reverse("teacher:gradebook", args=[pk]),
        },
    )


@role_required("TEACHER")
def assessment_delete(request, pk, assessment_id):
    offering = staff_offering(request.user, pk)
    assessment = get_object_or_404(Assessment, pk=assessment_id, offering=offering)
    return confirmation(
        request,
        f"Delete {assessment.title}",
        reverse("teacher:gradebook", args=[pk]),
        lambda reason: save_assessment(request.user, pk, {}, assessment_id, delete=True),
        description="Remove this assessment from the course.",
        consequences=[
            "The assessment disappears from the gradebook and from students' course pages.",
            "Only assessments without any grades can be deleted.",
        ],
        success_message=f"Assessment {assessment.title} deleted.",
        danger=True,
    )


@role_required("TEACHER")
def final_publish(request, pk, enrollment_id):
    offering = staff_offering(request.user, pk)
    enrollment = get_object_or_404(
        Enrollment, pk=enrollment_id, offering=offering, status="ENROLLED"
    )
    summary = grade_summary(enrollment)
    average = summary["average"] if summary["average"] is not None else "not available"
    proposed = f"{summary['proposed']}/10" if summary["proposed"] is not None else "not available"
    return confirmation(
        request,
        f"Publish final grade for {enrollment.student}",
        reverse("teacher:gradebook", args=[pk]),
        lambda reason: publish_final(request.user, pk, enrollment_id),
        description=f"Current average: {average}. Final grade: {proposed}, the average rounded "
        "half up. It is recalculated from the saved grades when you confirm.",
        consequences=[
            "The final grade appears on the student's course page and academic transcript.",
            "This student's grades are locked.",
            "While any final grade in this course is published, assessments cannot be added, "
            "edited or deleted.",
            "Only an administrator can unpublish a final grade to allow corrections.",
        ],
        success_message=lambda final: f"Final grade {final.value}/10 published for "
        f"{enrollment.student}.",
    )


@role_required("ADMIN")
def final_unpublish(request, pk, enrollment_id):
    offering = staff_offering(request.user, pk)
    enrollment = get_object_or_404(Enrollment, pk=enrollment_id, offering=offering)
    return confirmation(
        request,
        f"Unpublish final grade for {enrollment.student}",
        reverse("management:gradebook", args=[pk]),
        lambda reason: unpublish_final(request.user, pk, enrollment_id, reason),
        reason=True,
        description="Withdraw the published final grade so the teacher can correct this "
        "student's grades.",
        consequences=[
            "The student no longer sees a final grade for this course.",
            "The teacher can change this student's grades and publish a new final grade.",
        ],
        success_message=f"Final grade for {enrollment.student} unpublished. "
        "The teacher can now correct the grades.",
        reason_help="Recorded in the audit history. Not shown to the student.",
        danger=True,
    )


@role_required("ADMIN")
def grade_clear(request, pk, grade_id):
    offering = staff_offering(request.user, pk)
    grade = get_object_or_404(Grade, pk=grade_id, enrollment__offering=offering)
    return confirmation(
        request,
        f"Clear {grade.assessment.title} grade for {grade.enrollment.student}",
        reverse("management:gradebook", args=[pk]),
        lambda reason: clear_grade(request.user, pk, grade_id, reason),
        reason=True,
        description="Remove this assessment grade so the teacher can enter it again.",
        consequences=[
            "The grade is deleted and shows as Not graded.",
            "The teacher can enter a new grade for this assessment.",
        ],
        success_message="Grade cleared. The teacher can enter a new grade.",
        reason_help="Recorded in the audit history. Not shown to the student.",
        danger=True,
    )
