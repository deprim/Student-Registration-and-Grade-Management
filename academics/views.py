from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from accounts.models import User
from accounts.forms import RegistrationForm, UserEditForm
from accounts.services import review_student, set_user_active, save_user
from core.access import role_required
from core.models import AuditEvent
from core.ui import paginate, confirmation, form_errors
from grading.services import grade_summary
from .forms import ACADEMIC_FORMS
from .models import Semester, CourseOffering, Enrollment
from .services import ACADEMIC_MODELS, save_academic, archive_academic, enroll, withdraw


def filtered_offerings(request, queryset):
    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(course__title__icontains=query) | Q(course__code__icontains=query)
        )
    semester = request.GET.get("semester", "")
    if semester.isdigit():
        queryset = queryset.filter(semester_id=semester)
    return queryset.select_related("course", "semester", "teacher")


@role_required("STUDENT")
def catalog(request):
    offerings = CourseOffering.objects.filter(status="ACTIVE", semester__is_archived=False)
    return render(
        request,
        "academics/offerings.html",
        {
            "title": "Course catalog",
            "description": "Discover your next subject and reserve your place.",
            "page_obj": paginate(request, filtered_offerings(request, offerings)),
            "semesters": Semester.objects.all(),
        },
    )


@role_required("STUDENT")
def my_courses(request):
    offerings = CourseOffering.objects.filter(
        enrollments__student=request.user, enrollments__status="ENROLLED"
    ).exclude(status="DRAFT")
    return render(
        request,
        "academics/offerings.html",
        {
            "title": "My courses",
            "description": "Your current courses and academic history.",
            "page_obj": paginate(request, filtered_offerings(request, offerings)),
            "semesters": Semester.objects.all(),
        },
    )


def student_offering(user, pk):
    return get_object_or_404(
        CourseOffering.objects.select_related("course", "semester", "teacher")
        .filter(
            Q(status="ACTIVE")
            | Q(
                status="ARCHIVED",
                enrollments__student=user,
                enrollments__status="ENROLLED",
            )
        )
        .distinct(),
        pk=pk,
    )


@role_required("STUDENT")
def offering_detail(request, pk):
    offering = student_offering(request.user, pk)
    enrollment = Enrollment.objects.filter(
        student=request.user, offering=offering, status="ENROLLED"
    ).first()
    grades = {grade.assessment_id: grade for grade in enrollment.grades.all()} if enrollment else {}
    return render(
        request,
        "academics/detail.html",
        {
            "offering": offering,
            "enrollment": enrollment,
            "assessment_rows": [(item, grades.get(item.pk)) for item in offering.assessments.all()],
            "summary": grade_summary(enrollment) if enrollment else None,
            "can_enroll": not enrollment
            and offering.enrollment_is_open
            and offering.available_places > 0,
            "can_withdraw": bool(
                enrollment
                and offering.enrollment_is_open
                and not enrollment.grades.exists()
                and not hasattr(enrollment, "final_grade")
            ),
        },
    )


@role_required("STUDENT")
def enrollment_action(request, pk, action):
    offering = student_offering(request.user, pk)
    if action == "withdraw":
        get_object_or_404(Enrollment, student=request.user, offering=offering, status="ENROLLED")
    elif action != "enroll":
        from django.http import Http404

        raise Http404
    return confirmation(
        request,
        f"{'Withdraw from' if action == 'withdraw' else 'Enroll in'} {offering.course.title}",
        reverse("student:offering", args=[pk]),
        lambda reason: (withdraw if action == "withdraw" else enroll)(request.user, pk),
        description="Your academic record will be preserved."
        if action == "withdraw"
        else "Enrollment is immediate when an available place remains.",
    )


@role_required("TEACHER")
def teacher_offerings(request):
    offerings = CourseOffering.objects.filter(teacher=request.user)
    return render(
        request,
        "academics/offerings.html",
        {
            "title": "Assigned courses",
            "description": "Manage assessments and support your students.",
            "page_obj": paginate(request, filtered_offerings(request, offerings)),
            "semesters": Semester.objects.all(),
        },
    )


@role_required("ADMIN")
def users(request):
    queryset = User.objects.all().select_related("student_profile")
    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(student_profile__student_number__icontains=query)
        )
    if request.GET.get("status") in User.Approval.values:
        queryset = queryset.filter(role="STUDENT", approval_status=request.GET["status"])
    if request.GET.get("role") in User.Role.values:
        queryset = queryset.filter(role=request.GET["role"])
    return render(
        request,
        "management/users.html",
        {"title": "People & applications", "page_obj": paginate(request, queryset)},
    )


@role_required("ADMIN")
def user_edit(request, pk=None):
    user = get_object_or_404(User, pk=pk) if pk else None
    form = (
        UserEditForm(request.POST if request.method == "POST" else None, instance=user)
        if user
        else RegistrationForm(request.POST if request.method == "POST" else None)
    )
    if request.method == "POST" and form.is_valid():
        try:
            save_user(request.user, form.cleaned_data, pk)
        except ValidationError as error:
            form_errors(form, error)
        else:
            messages.success(request, "The user profile has been saved.")
            return redirect("management:users")
    return render(
        request,
        "core/form.html",
        {
            "form": form,
            "title": "Edit user" if pk else "Create teacher",
            "back_url": reverse("management:users"),
        },
    )


@role_required("ADMIN")
def user_action(request, pk, action):
    user = get_object_or_404(User, pk=pk)
    from django.http import Http404

    if action in ["approve", "reject"]:
        if user.role != "STUDENT":
            raise Http404

        def operation(reason):
            return review_student(request.user, pk, action == "approve", reason)
    elif action in ["block", "unblock"]:

        def operation(reason):
            return set_user_active(request.user, pk, action == "unblock", reason)
    else:
        raise Http404
    return confirmation(
        request,
        f"{action.capitalize()} {user}",
        reverse("management:users"),
        operation,
        reason=action != "approve",
    )


@role_required("ADMIN")
def academic_list(request, kind):
    if kind not in ACADEMIC_MODELS:
        from django.http import Http404

        raise Http404
    queryset = ACADEMIC_MODELS[kind].objects.all()
    query = request.GET.get("q", "").strip()
    if kind == "offerings":
        queryset = filtered_offerings(request, queryset)
    elif query:
        queryset = (
            queryset.filter(name__icontains=query)
            if kind == "semesters"
            else queryset.filter(Q(title__icontains=query) | Q(code__icontains=query))
        )
    page = paginate(request, queryset)
    rows = []
    for obj in page:
        if kind == "semesters":
            cells = [
                obj.name,
                f"{obj.start_date} — {obj.end_date}",
                "Archived" if obj.is_archived else "Current",
            ]
        elif kind == "courses":
            cells = [obj.code, obj.title, "Archived" if obj.is_archived else "Current"]
        else:
            cells = [
                str(obj.course),
                str(obj.semester),
                str(obj.teacher),
                f"{obj.enrolled_count}/{obj.capacity}",
                obj.get_status_display(),
            ]
        rows.append(
            {
                "obj": obj,
                "cells": cells,
                "archived": obj.status == "ARCHIVED" if kind == "offerings" else obj.is_archived,
            }
        )
    headings = {
        "semesters": ["Semester", "Dates", "Status"],
        "courses": ["Code", "Title", "Status"],
        "offerings": ["Course", "Semester", "Teacher", "Places", "Status"],
    }
    return render(
        request,
        "management/academic_list.html",
        {
            "title": kind.capitalize(),
            "kind": kind,
            "rows": rows,
            "headings": headings[kind],
            "page_obj": page,
        },
    )


@role_required("ADMIN")
def academic_edit(request, kind, pk=None):
    if kind not in ACADEMIC_MODELS:
        from django.http import Http404

        raise Http404
    obj = get_object_or_404(ACADEMIC_MODELS[kind], pk=pk) if pk else None
    form = ACADEMIC_FORMS[kind](request.POST if request.method == "POST" else None, instance=obj)
    if request.method == "POST" and form.is_valid():
        try:
            save_academic(request.user, kind, form.cleaned_data, pk)
        except ValidationError as error:
            form_errors(form, error)
        else:
            messages.success(request, "The academic record has been saved.")
            return redirect("management:academic_list", kind=kind)
    return render(
        request,
        "core/form.html",
        {
            "form": form,
            "title": f"{'Edit' if pk else 'Create'} {kind[:-1]}",
            "back_url": reverse("management:academic_list", args=[kind]),
        },
    )


@role_required("ADMIN")
def academic_archive(request, kind, pk):
    if kind not in ACADEMIC_MODELS:
        from django.http import Http404

        raise Http404
    obj = get_object_or_404(ACADEMIC_MODELS[kind], pk=pk)
    return confirmation(
        request,
        f"Archive {obj}",
        reverse("management:academic_list", args=[kind]),
        lambda reason: archive_academic(request.user, kind, pk),
        description="Archived records become read-only.",
    )


@role_required("ADMIN")
def audit_history(request):
    events = AuditEvent.objects.select_related("actor")
    if request.GET.get("q"):
        events = events.filter(
            Q(action__icontains=request.GET["q"])
            | Q(target__icontains=request.GET["q"])
            | Q(actor__email__icontains=request.GET["q"])
        )
    return render(
        request,
        "management/audit.html",
        {"title": "Audit history", "page_obj": paginate(request, events)},
    )
