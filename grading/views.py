from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.forms import formset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from academics.models import Enrollment
from core.access import role_required, staff_offering
from core.ui import paginate, confirmation, form_errors
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
        rows.append({"enrollment": enrollment, "summary": summary, "cells": cells})
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
            messages.success(request, "Grades have been saved.")
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
            messages.success(request, "The assessment has been saved.")
            return redirect("teacher:gradebook", pk=pk)
    return render(
        request,
        "core/form.html",
        {
            "title": "Edit assessment" if assessment_id else "Create assessment",
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
    )


@role_required("TEACHER")
def final_publish(request, pk, enrollment_id):
    offering = staff_offering(request.user, pk)
    enrollment = get_object_or_404(
        Enrollment, pk=enrollment_id, offering=offering, status="ENROLLED"
    )
    summary = grade_summary(enrollment)
    return confirmation(
        request,
        f"Publish final grade for {enrollment.student}",
        reverse("teacher:gradebook", args=[pk]),
        lambda reason: publish_final(request.user, pk, enrollment_id),
        description=f"Current average: {summary['average'] if summary['average'] is not None else 'Not graded'}. Proposed final: {summary['proposed'] if summary['proposed'] is not None else 'Not available'}. The final will be recalculated from saved grades when confirmed.",
    )


@role_required("ADMIN")
def final_unpublish(request, pk, enrollment_id):
    staff_offering(request.user, pk)
    return confirmation(
        request,
        "Unpublish final grade",
        reverse("management:gradebook", args=[pk]),
        lambda reason: unpublish_final(request.user, pk, enrollment_id, reason),
        reason=True,
    )


@role_required("ADMIN")
def grade_clear(request, pk, grade_id):
    offering = staff_offering(request.user, pk)
    get_object_or_404(Grade, pk=grade_id, enrollment__offering=offering)
    return confirmation(
        request,
        "Clear assessment grade",
        reverse("management:gradebook", args=[pk]),
        lambda reason: clear_grade(request.user, pk, grade_id, reason),
        reason=True,
    )
