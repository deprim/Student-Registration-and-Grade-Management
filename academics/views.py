from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import dateformat
from accounts.models import User
from accounts.forms import RegistrationForm, UserEditForm
from accounts.services import review_student, set_user_active, save_user
from core.access import role_required
from core.models import AuditEvent
from core.ui import paginate, confirmation, form_errors, enrollment_window
from grading.services import grade_summary
from .forms import ACADEMIC_FORMS
from .models import Semester, Course, CourseOffering, Enrollment
from .services import ACADEMIC_MODELS, save_academic, archive_academic, enroll, withdraw

ACADEMIC_PAGES = {
    "semesters": {
        "title": "Semesters",
        "step": 1,
        "create": "Create semester",
        "edit": "Edit semester",
        "saved": "Semester saved.",
        "description": "A semester is a named teaching period with start and end dates. "
        "Create the semester first: every course offering belongs to one semester.",
        "empty": "No semesters yet. Create the first semester to start building "
        "the academic structure.",
    },
    "courses": {
        "title": "Course library",
        "step": 2,
        "create": "Add course to library",
        "edit": "Edit library course",
        "saved": "Library course saved.",
        "description": "The course library holds permanent course descriptions, such as "
        "CS101 Introduction to Programming. A library course has no teacher, dates or "
        "students until you create a course offering for it.",
        "empty": "The course library is empty. Add the first course, for example CS101.",
    },
    "offerings": {
        "title": "Course offerings",
        "step": 3,
        "create": "Create course offering",
        "edit": "Edit course offering",
        "saved": "Course offering saved.",
        "description": "A course offering is one library course taught in one semester by "
        "one teacher, with a capacity and an enrollment window. Students enroll in "
        "offerings, and teachers grade them.",
        "empty": "No course offerings yet.",
    },
}
ARCHIVE_CONSEQUENCES = {
    "offerings": [
        "Allowed only after enrollment has closed and every enrolled student has a "
        "published final grade.",
        "The offering becomes permanently read-only: grades, final grades and settings "
        "can no longer change.",
        "Enrolled students keep seeing the course and their final grade in their history.",
        "Archiving cannot be undone.",
    ],
    "semesters": [
        "Allowed only after every course offering in this semester is archived.",
        "The semester disappears from the course catalog and from new offering forms.",
        "Archiving cannot be undone.",
    ],
    "courses": [
        "Allowed only after every offering of this course is archived.",
        "The course can no longer be used for new course offerings.",
        "Archiving cannot be undone.",
    ],
}


def setup_steps(current_kind):
    return [
        {
            "number": page["step"],
            "title": page["title"],
            "url": reverse("management:academic_list", args=[kind]),
            "current": kind == current_kind,
        }
        for kind, page in ACADEMIC_PAGES.items()
    ]


def offering_prerequisites():
    """Show what must exist before an offering can be created (the form enforces it)."""
    items = [
        {
            "label": "A current semester",
            "done": Semester.objects.filter(is_archived=False).exists(),
            "url": reverse("management:academic_create", args=["semesters"]),
            "action": "Create semester",
        },
        {
            "label": "A course in the course library",
            "done": Course.objects.filter(is_archived=False).exists(),
            "url": reverse("management:academic_create", args=["courses"]),
            "action": "Add course to library",
        },
        {
            "label": "An active teacher account",
            "done": User.objects.filter(role="TEACHER", is_active=True).exists(),
            "url": reverse("management:teacher_create"),
            "action": "Create teacher",
        },
    ]
    return items if not all(item["done"] for item in items) else []


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


def catalog_availability(offering, enrolled_ids):
    """Label a catalog card using the same rules as the course page's enroll button."""
    if offering.pk in enrolled_ids:
        return "You are enrolled", "enrolled"
    if not offering.enrollment_is_open:
        return "Enrollment closed", "neutral"
    if offering.available_places == 0:
        return "Enrollment full", "warning"
    return "Open for enrollment", ""


@role_required("STUDENT")
def catalog(request):
    offerings = CourseOffering.objects.filter(status="ACTIVE", semester__is_archived=False)
    page = paginate(request, filtered_offerings(request, offerings))
    enrolled_ids = set(
        Enrollment.objects.filter(
            student=request.user,
            status=Enrollment.Status.ENROLLED,
            offering__in=[offering.pk for offering in page],
        ).values_list("offering_id", flat=True)
    )
    for offering in page:
        offering.availability, offering.availability_class = catalog_availability(
            offering, enrolled_ids
        )
    return render(
        request,
        "academics/offerings.html",
        {
            "title": "Course catalog",
            "description": "Find a course and check whether you can enroll. Open a course "
            "to see its details and enrollment dates.",
            "page_obj": page,
            "semesters": Semester.objects.filter(is_archived=False),
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
            "description": "Your current courses and academic history. Open a course to see "
            "your grades and your teacher's comments.",
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
    has_results = bool(
        enrollment and (enrollment.grades.exists() or hasattr(enrollment, "final_grade"))
    )
    can_withdraw = bool(enrollment and offering.enrollment_is_open and not has_results)
    withdraw_note = ""
    if enrollment and not can_withdraw:
        withdraw_note = (
            "Withdrawal is no longer possible because grades have already been recorded "
            "for you in this course."
            if has_results
            else "Withdrawal is no longer possible because enrollment for this course is closed."
        )
    window = enrollment_window(offering)
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
            "can_withdraw": can_withdraw,
            "withdraw_note": withdraw_note,
            "window": window,
            "back_url": reverse("student:courses" if enrollment else "student:catalog"),
            "back_label": "Back to my courses" if enrollment else "Back to course catalog",
        },
    )


@role_required("STUDENT")
def enrollment_action(request, pk, action):
    offering = student_offering(request.user, pk)
    title = offering.course.title
    if action == "withdraw":
        get_object_or_404(Enrollment, student=request.user, offering=offering, status="ENROLLED")
        return confirmation(
            request,
            f"Withdraw from {title}",
            reverse("student:offering", args=[pk]),
            lambda reason: withdraw(request.user, pk),
            description="You will leave this course and free your place for another student.",
            consequences=[
                "You can enroll again later while enrollment is open and a place is available.",
                "If you enroll again, your original enrollment record is restored.",
            ],
            success_message=f"You have withdrawn from {title}.",
            danger=True,
        )
    if action != "enroll":
        from django.http import Http404

        raise Http404
    return confirmation(
        request,
        f"Enroll in {title}",
        reverse("student:offering", args=[pk]),
        lambda reason: enroll(request.user, pk),
        description="Your place is reserved immediately if one is still available.",
        consequences=[
            f"Your teacher, {offering.teacher}, will see you in the course gradebook.",
            "You can withdraw while enrollment is open, until your first grade is recorded.",
        ],
        success_message=f"You are enrolled in {title}.",
    )


@role_required("TEACHER")
def teacher_offerings(request):
    offerings = CourseOffering.objects.filter(teacher=request.user)
    page = paginate(request, filtered_offerings(request, offerings))
    for offering in page:
        offering.window = enrollment_window(offering)
    return render(
        request,
        "academics/offerings.html",
        {
            "title": "Assigned courses",
            "description": "Course offerings assigned to you. Open a gradebook to add "
            "assessments, record grades and publish final grades.",
            "page_obj": page,
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
            saved = save_user(request.user, form.cleaned_data, pk)
        except ValidationError as error:
            form_errors(form, error)
        else:
            messages.success(
                request,
                f"Details saved for {saved}."
                if pk
                else f"Teacher account created for {saved.email}. They can sign in now.",
            )
            return redirect("management:users")
    return render(
        request,
        "core/form.html",
        {
            "form": form,
            "title": "Edit user details" if pk else "Create teacher account",
            "description": f"Account email: {user.email}"
            if pk
            else "Teachers sign in with this email and password. They see only the course "
            "offerings an administrator assigns to them.",
            "back_url": reverse("management:users"),
        },
    )


def user_action_text(user, action):
    if action == "approve":
        return (
            "Approve the application so this student can use the full student workspace.",
            [
                "The student can browse the course catalog and enroll in courses.",
                "A permanent student number is assigned.",
                "No email is sent. The student sees the change on their Application status page.",
            ],
            "",
        )
    if action == "reject":
        return (
            "Reject this application. The student keeps an account but cannot enroll.",
            [
                "Your reason is shown to the student on their Application status page, "
                "so write it clearly.",
                "You can still approve this student later from People & applications.",
            ],
            "Shown to the student.",
        )
    if action == "block":
        consequences = [
            "The user is signed out immediately and cannot sign in.",
            "Enrollments, grades and occupied course places are kept.",
            "You can unblock the user at any time.",
        ]
        if user.role == "TEACHER":
            consequences.insert(
                2, "A blocked teacher cannot be assigned to new course offerings."
            )
        return (
            "Block this account to stop all access.",
            consequences,
            "Recorded in the audit history. Not shown to the user.",
        )
    return (
        "Restore access to this account.",
        ["The user can sign in again with their existing password."],
        "Recorded in the audit history.",
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
    description, consequences, reason_help = user_action_text(user, action)
    success = {
        "approve": lambda student: f"{student} has been approved. Student number: "
        f"{student.student_profile.student_number}.",
        "reject": f"The application from {user} has been rejected. "
        "The student will see your reason.",
        "block": f"{user} has been blocked and signed out.",
        "unblock": f"{user} has been unblocked and can sign in again.",
    }[action]
    return confirmation(
        request,
        f"{action.capitalize()} {user}",
        reverse("management:users"),
        operation,
        reason=action != "approve",
        description=description,
        consequences=consequences,
        success_message=success,
        reason_help=reason_help,
        danger=action in ["reject", "block"],
    )


def academic_cells(kind, obj):
    if kind == "semesters":
        return [
            {"text": obj.name},
            {
                "text": f"{dateformat.format(obj.start_date, 'M j, Y')} – "
                f"{dateformat.format(obj.end_date, 'M j, Y')}"
            },
            {"badge": "Archived", "tone": "neutral"}
            if obj.is_archived
            else {"badge": "Current", "tone": ""},
        ]
    if kind == "courses":
        return [
            {"text": obj.code, "strong": True},
            {"text": obj.title},
            {"badge": "Archived", "tone": "neutral"}
            if obj.is_archived
            else {"badge": "Current", "tone": ""},
        ]
    enrolled = obj.enrolled_count
    status = {
        "DRAFT": {"badge": "Draft", "tone": "warning", "detail": "Hidden from students"},
        "ACTIVE": {"badge": "Active", "tone": "", "detail": "Visible in the catalog"},
        "ARCHIVED": {"badge": "Archived", "tone": "neutral", "detail": "Read-only"},
    }[obj.status]
    window = enrollment_window(obj)
    return [
        {"text": obj.course.title, "detail": obj.course.code, "strong": True},
        {"text": str(obj.semester)},
        {"text": str(obj.teacher)},
        {
            "text": f"{enrolled} / {obj.capacity}",
            "detail": "Full" if enrolled >= obj.capacity else f"{obj.capacity - enrolled} free",
        },
        {"badge": window["label"], "tone": window["tone"], "detail": window["detail"]},
        status,
    ]


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
    rows = [
        {
            "obj": obj,
            "cells": academic_cells(kind, obj),
            "archived": obj.status == "ARCHIVED" if kind == "offerings" else obj.is_archived,
        }
        for obj in page
    ]
    headings = {
        "semesters": ["Semester", "Dates", "Status"],
        "courses": ["Code", "Title", "Status"],
        "offerings": ["Course", "Semester", "Teacher", "Places", "Enrollment", "Status"],
    }
    return render(
        request,
        "management/academic_list.html",
        {
            "page": ACADEMIC_PAGES[kind],
            "title": ACADEMIC_PAGES[kind]["title"],
            "kind": kind,
            "rows": rows,
            "headings": headings[kind],
            "page_obj": page,
            "steps": setup_steps(kind),
            "prerequisites": offering_prerequisites() if kind == "offerings" else [],
            "searching": bool(request.GET.get("q") or request.GET.get("semester")),
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
            messages.success(request, ACADEMIC_PAGES[kind]["saved"])
            return redirect("management:academic_list", kind=kind)
    page = ACADEMIC_PAGES[kind]
    return render(
        request,
        "core/form.html",
        {
            "form": form,
            "title": page["edit"] if pk else page["create"],
            "description": page["description"],
            "back_url": reverse("management:academic_list", args=[kind]),
            "prerequisites": offering_prerequisites() if kind == "offerings" and not pk else [],
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
        description="Archive finished records to keep them as read-only history.",
        consequences=ARCHIVE_CONSEQUENCES[kind],
        success_message=f"{obj} has been archived and is now read-only.",
        danger=True,
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
